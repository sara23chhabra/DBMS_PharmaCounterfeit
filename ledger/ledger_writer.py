"""
Ledger writer (Person A): seals MySQL records into the hash chain in MongoDB.

Run from the repository root:
    python -m ledger.ledger_writer            seal everything not yet sealed
    python -m ledger.ledger_writer --sample   also write ledger/sample_blocks.json
                                              (all blocks of one sold pack, for Person B)

What it does
  1. Reads every lot, batch and event with ledger_synced = FALSE.
  2. Groups them into blocks (team contract 3.3):
       LOT_RECEIPT  one per lot                      ref_key lot:<lot_id>
       PRODUCTION   one per batch (batch hash first,
                    then its MANUFACTURED events)    ref_key batch:<batch_id>
       DISPATCH     one per shipment                 ref_key shipment:<id>:D
       RECEIPT      one per received shipment        ref_key shipment:<id>:R
       SALE         50 SOLD events in time order     ref_key sale:<first event_id>
       RECALL       one per recalled batch           ref_key recall:<batch_id>:<n>
  3. Sorts the blocks by time and chains them: each block stores the
     previous block's hash, and its own hash covers its content plus that
     previous hash. Changing any old record breaks every later block.
  4. Saves each block in MongoDB, then marks its rows ledger_synced = TRUE.

Safe to run again (idempotent)
  A block is saved with an upsert on its unique ref_key. If the program
  stops after saving a block but before marking its rows, the next run
  finds the block already there, marks the rows it contains, and moves on.
  A second run on a fully sealed database writes nothing.
"""

import argparse
import json
import os
import re
from collections import defaultdict

from common.config import get_mongo_db, get_mysql
from common.hashing import GENESIS_HASH, block_hash

SALE_BLOCK_SIZE = 50
COMMIT_EVERY = 200
TYPE_ORDER = {"LOT_RECEIPT": 0, "PRODUCTION": 1, "DISPATCH": 2, "RECEIPT": 3, "SALE": 4, "RECALL": 5}
TABLE_OF_KIND = {"lot": ("material_lot", "lot_id"), "batch": ("batch", "batch_id"),
                 "event": ("trace_event", "event_id")}


def ts(value):
    """date or datetime -> 'YYYY-MM-DD HH:MM:SS' (a date becomes midnight)."""
    if hasattr(value, "hour"):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return value.strftime("%Y-%m-%d") + " 00:00:00"


def event_item(e):
    return {"kind": "event", "id": e["event_id"], "serial_no": e["serial_no"],
            "event_type": e["event_type"], "hash": e["event_hash"]}


# ---------------------------------------------------------------------
# 1. Read
# ---------------------------------------------------------------------
def fetch_unsynced(conn):
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT lot_id, received_date, lot_hash FROM material_lot "
                "WHERE ledger_synced = FALSE ORDER BY lot_id")
    lots = cur.fetchall()
    cur.execute("SELECT batch_id, mfg_date, batch_hash FROM batch "
                "WHERE ledger_synced = FALSE ORDER BY batch_id")
    batches = cur.fetchall()
    cur.execute("SELECT e.event_id, e.serial_no, e.event_type, e.shipment_id, e.event_time, "
                "       e.event_hash, p.batch_id "
                "FROM trace_event e LEFT JOIN pack p ON p.serial_no = e.serial_no "
                "WHERE e.ledger_synced = FALSE ORDER BY e.event_id")
    events = cur.fetchall()
    cur.close()
    return lots, batches, events


# ---------------------------------------------------------------------
# 2. Group into blocks (pure function: no database needed, easy to test)
# ---------------------------------------------------------------------
def build_blocks(lots, batches, events, recall_counts=None):
    """
    Returns (blocks, warnings). Each block has block_type, ref_key,
    timestamp and items; index and hashes are added when it is sealed.
    recall_counts: {batch_id: number of RECALL blocks already in the ledger}.
    """
    recall_counts = recall_counts or {}
    blocks, warnings = [], []

    for lot in lots:
        if not lot["lot_hash"]:
            warnings.append(f"lot {lot['lot_id']} has no hash; skipped")
            continue
        blocks.append({"block_type": "LOT_RECEIPT", "ref_key": f"lot:{lot['lot_id']}",
                       "timestamp": ts(lot["received_date"]),
                       "items": [{"kind": "lot", "id": lot["lot_id"], "hash": lot["lot_hash"]}]})

    manufactured = defaultdict(list)      # batch_id -> events
    dispatched = defaultdict(list)        # shipment_id -> events
    received = defaultdict(list)          # shipment_id -> events
    recalled = defaultdict(list)          # batch_id -> events
    sold = []
    for e in events:
        if not e["event_hash"]:
            warnings.append(f"event {e['event_id']} has no hash; skipped")
        elif e["event_type"] == "MANUFACTURED":
            manufactured[e["batch_id"]].append(e)
        elif e["event_type"] == "DISPATCHED":
            dispatched[e["shipment_id"]].append(e)
        elif e["event_type"] == "RECEIVED":
            received[e["shipment_id"]].append(e)
        elif e["event_type"] == "SOLD":
            sold.append(e)
        elif e["event_type"] == "RECALLED":
            recalled[e["batch_id"]].append(e)

    unsynced_batches = set()
    for b in batches:
        unsynced_batches.add(b["batch_id"])
        evs = manufactured.get(b["batch_id"], [])
        if not b["batch_hash"]:
            warnings.append(f"batch {b['batch_id']} has no hash; skipped")
        elif not evs:
            # Batch created but packs not generated yet: sealed on a later run,
            # together with its MANUFACTURED events.
            warnings.append(f"batch {b['batch_id']} has no packs yet; left for a later run")
        else:
            items = [{"kind": "batch", "id": b["batch_id"], "hash": b["batch_hash"]}]
            items += [event_item(e) for e in evs]
            blocks.append({"block_type": "PRODUCTION", "ref_key": f"batch:{b['batch_id']}",
                           "timestamp": ts(max(e["event_time"] for e in evs)), "items": items})
    for batch_id in manufactured:
        if batch_id not in unsynced_batches:
            warnings.append(f"MANUFACTURED events of batch {batch_id} found after its block was sealed; skipped")

    for label, suffix, groups in (("DISPATCH", "D", dispatched), ("RECEIPT", "R", received)):
        for shipment_id, evs in groups.items():
            blocks.append({"block_type": label, "ref_key": f"shipment:{shipment_id}:{suffix}",
                           "timestamp": ts(max(e["event_time"] for e in evs)),
                           "items": [event_item(e) for e in evs]})

    for i in range(0, len(sold), SALE_BLOCK_SIZE):       # sold is in event_id (= time) order
        evs = sold[i:i + SALE_BLOCK_SIZE]
        blocks.append({"block_type": "SALE", "ref_key": f"sale:{evs[0]['event_id']}",
                       "timestamp": ts(max(e["event_time"] for e in evs)),
                       "items": [event_item(e) for e in evs]})

    for batch_id, evs in recalled.items():
        n = recall_counts.get(batch_id, 0) + 1
        blocks.append({"block_type": "RECALL", "ref_key": f"recall:{batch_id}:{n}",
                       "timestamp": ts(max(e["event_time"] for e in evs)),
                       "items": [event_item(e) for e in evs]})

    blocks.sort(key=lambda b: (b["timestamp"], TYPE_ORDER[b["block_type"]], b["ref_key"]))
    return blocks, warnings


def seal(block, block_index, prev_block_hash):
    """Give a block its place in the chain and its hash."""
    block["block_index"] = block_index
    block["prev_block_hash"] = prev_block_hash
    block["block_hash"] = block_hash(block_index, block["timestamp"], block["block_type"],
                                     [it["hash"] for it in block["items"]], prev_block_hash)
    return block


# ---------------------------------------------------------------------
# 3. Write
# ---------------------------------------------------------------------
def mark_synced(cur, items):
    ids = defaultdict(list)
    for it in items:
        ids[it["kind"]].append(it["id"])
    for kind, id_list in ids.items():
        table, column = TABLE_OF_KIND[kind]
        marks = ",".join(["%s"] * len(id_list))
        cur.execute(f"UPDATE {table} SET ledger_synced = TRUE WHERE {column} IN ({marks})", id_list)


def run():
    conn = get_mysql()
    col = get_mongo_db()["ledger_blocks"]
    col.create_index("block_index", unique=True)
    col.create_index("ref_key", unique=True)
    col.create_index("items.id")
    scans = get_mongo_db()["scan_logs"]
    scans.create_index("serial_no")
    scans.create_index("scanned_at")

    lots, batches, events = fetch_unsynced(conn)
    recall_counts = defaultdict(int)
    for doc in col.find({"block_type": "RECALL"}, {"ref_key": 1}):
        m = re.match(r"recall:(\d+):", doc["ref_key"])
        if m:
            recall_counts[int(m.group(1))] += 1
    blocks, warnings = build_blocks(lots, batches, events, recall_counts)
    for w in warnings:
        print("  note:", w)

    last = col.find_one(sort=[("block_index", -1)])
    index = last["block_index"] if last else -1
    prev = last["block_hash"] if last else GENESIS_HASH

    print(f"Unsealed rows: {len(lots)} lots, {len(batches)} batches, {len(events)} events "
          f"-> {len(blocks)} blocks to write")
    cur = conn.cursor()
    written = defaultdict(int)
    for n, block in enumerate(blocks, 1):
        seal(block, index + 1, prev)
        result = col.update_one({"ref_key": block["ref_key"]}, {"$setOnInsert": block}, upsert=True)
        if result.upserted_id is not None:           # new block: the chain moves on
            index, prev = block["block_index"], block["block_hash"]
            written[block["block_type"]] += 1
            mark_synced(cur, block["items"])
        else:                                        # sealed by an earlier, interrupted run
            existing = col.find_one({"ref_key": block["ref_key"]})
            mark_synced(cur, existing["items"])
        if n % COMMIT_EVERY == 0:
            conn.commit()
            print(f"  {n} / {len(blocks)}")
    conn.commit()
    cur.close()
    conn.close()

    print("Blocks written:", ", ".join(f"{k} {written[k]}" for k in TYPE_ORDER if written[k]) or "none")
    print(f"Ledger now holds {col.count_documents({})} blocks; last index {index}, last hash {prev}")
    return col


def write_sample(col):
    """All blocks that mention one sold pack, as JSON, for building verify.py."""
    sale = col.find_one({"block_type": "SALE"}, sort=[("block_index", 1)])
    if not sale:
        print("No SALE block yet; no sample written")
        return
    serial = sale["items"][0]["serial_no"]
    docs = list(col.find({"items.serial_no": serial}, {"_id": 0}).sort("block_index", 1))
    path = os.path.join(os.path.dirname(__file__), "sample_blocks.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"serial_no": serial, "blocks": docs}, f, indent=1)
    print(f"Sample: {len(docs)} blocks for serial {serial} -> {path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seal unsynced MySQL records into the MongoDB ledger")
    parser.add_argument("--sample", action="store_true", help="also write ledger/sample_blocks.json")
    args = parser.parse_args()
    collection = run()
    if args.sample:
        write_sample(collection)
