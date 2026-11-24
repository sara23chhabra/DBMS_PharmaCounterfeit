"""
The one place that defines how hashes are computed (team contract 3.2, 3.3).

Used by the ledger writer (Person A) and by verification and
reconciliation (Person B). The same strings are built in SQL by
03_procedures.sql, and in the seed by generate_data.py; all three must
give identical results.

Canonical string: fields joined with '|'
  NULL      -> ''
  DATE      -> YYYY-MM-DD
  DATETIME  -> YYYY-MM-DD HH:MM:SS
  DECIMAL   -> 2 decimal places
  BOOLEAN   -> 1 / 0
Hash: SHA-256, lowercase hex, 64 characters.
"""

import hashlib
from datetime import date, datetime
from decimal import Decimal

GENESIS_HASH = "0" * 64      # prev_block_hash of the very first block


def canon(*values):
    """Join values into the canonical string."""
    out = []
    for v in values:
        if v is None:
            out.append("")
        elif isinstance(v, bool):
            out.append("1" if v else "0")
        elif isinstance(v, datetime):
            out.append(v.strftime("%Y-%m-%d %H:%M:%S"))
        elif isinstance(v, date):
            out.append(v.strftime("%Y-%m-%d"))
        elif isinstance(v, Decimal):
            out.append(f"{v:.2f}")
        else:
            out.append(str(v))
    return "|".join(out)


def sha256_hex(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def lot_hash(lot_id, lot_no, material_name, quantity_sent_kg, quantity_received_kg,
             supplier_id, manufacturer_id, received_date, coa_verified):
    """Pass the two quantities as Decimal (what MySQL returns)."""
    return sha256_hex(canon(lot_id, lot_no, material_name, quantity_sent_kg,
                            quantity_received_kg, supplier_id, manufacturer_id,
                            received_date, int(coa_verified)))


def batch_hash(batch_id, drug_id, manufacturer_id, batch_no, mfg_date, expiry_date,
               quantity, lot_ids):
    """lot_ids: any list of the batch's lot IDs; sorted here. qc_status is not hashed."""
    lots = ",".join(str(x) for x in sorted(set(int(x) for x in lot_ids)))
    return sha256_hex(canon(batch_id, drug_id, manufacturer_id, batch_no, mfg_date,
                            expiry_date, quantity, lots))


def event_hash(event_id, serial_no, event_type, from_id, to_id, shipment_id, event_time):
    """
    from_id / to_id:
      DISPATCHED, RECEIVED, SOLD -> the shipment's link (from_participant, to_participant)
      MANUFACTURED               -> both = the batch's manufacturer; shipment_id None
      RECALLED                   -> both = pack.current_owner;       shipment_id None
    """
    return sha256_hex(canon(event_id, serial_no, event_type, from_id, to_id,
                            shipment_id, event_time))


def block_hash(block_index, timestamp, block_type, item_hashes, prev_block_hash):
    """timestamp is the string stored in the block ('YYYY-MM-DD HH:MM:SS')."""
    return sha256_hex(canon(block_index, timestamp, block_type,
                            ",".join(item_hashes), prev_block_hash))
