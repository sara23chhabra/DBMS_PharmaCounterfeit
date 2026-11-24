#!/usr/bin/env python3
"""
=====================================================================
Pharma Supply Chain DBMS Project
generate_data.py : seed data generator (9 months of simulated history)

What it does
  Invents a whole supply chain (Jan 1 - Sep 30, 2026): participants,
  licenses, drugs, raw-material lots, batches, ~50,000 packs, every
  shipment, receipt and sale, plus deliberately planted counterfeits
  (recorded in injected_counterfeit, the answer key).

Output (written into ./output/)
  seed_data.sql   -> load into MySQL from a terminal:
                       mysql -u root -p pharma_counterfeit_db < output/seed_data.sql
  scan_logs.json  -> load into MongoDB:
                       mongoimport --db pharma_counterfeit_db --collection scan_logs --file output/scan_logs.json

Run
  python generate_data.py            (Python 3.8+, standard library only)

Same SEED -> exactly the same data every time. Commit this script,
git-ignore the output/ folder.

Hash format (Python and MySQL must agree):
  fields joined with '|', NULL -> '', DATE 'YYYY-MM-DD',
  DATETIME 'YYYY-MM-DD HH:MM:SS', DECIMAL with 2 places, BOOLEAN 1/0.
  lot_hash   = lot_id|lot_no|material_name|quantity_sent_kg|quantity_received_kg|
               supplier_id|manufacturer_id|received_date|coa_verified
  batch_hash = batch_id|drug_id|manufacturer_id|batch_no|mfg_date|expiry_date|
               quantity|<lot IDs sorted ascending, joined with ','>
  event_hash = event_id|serial_no|event_type|from|to|shipment_id|event_time
               from/to come from shipment -> link; for MANUFACTURED and
               RECALLED (no shipment) from = to = the holder.
=====================================================================
"""

import argparse
import hashlib
import json
import math
import os
import random
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP

# =====================================================================
# 1. SETTINGS (change here, not in the code below)
# =====================================================================
SEED = 42
START = datetime(2026, 1, 1, 0, 0, 0)
END = datetime(2026, 9, 30, 23, 59, 59)
LABEL_START = datetime(2026, 7, 1)        # Jan-Jun = AI features, Jul-Sep = AI labels
NEW_LICENSE_SINCE = date(2025, 1, 1)      # "new license" = issued in the year before the simulation

N_DISTRIBUTORS = 15
N_RETAILERS = 80
BATCHES_PER_MANUFACTURER = 50
FIRST_BATCH_DAY = date(2026, 1, 20)
LAST_BATCH_DAY = date(2026, 9, 12)
PACKS_PER_BATCH = (220, 450)              # ~50,000 packs in total
MD_SHIPMENT_SIZE = (100, 300)             # manufacturer -> distributor
DR_SHIPMENT_SIZE = (10, 50)               # distributor -> retailer
SALE_DELAY_MEAN_DAYS = 45                 # average days a pack sits on a pharmacy shelf

# Counterfeit injection. Each chance is multiplied by the link's hidden
# risk (0..1), so risky links get more counterfeits, but never always.
P_SWAP = 0.06               # per shipment: genuine packs removed, fakes added
P_INVENTED = 0.04           # per D->R shipment: extra packs with invented serials
P_STAGE_SKIP = 0.02         # per D->R shipment: packs that never went through a distributor
P_FAKE_LOT = 0.04           # per material lot: CoA not verified or overweight
P_SHIP_TO_SUSPENDED = 0.6   # chance (x (0.5 + risk)) a party still deals with a suspended one
CLONES_PER_RETAILER = 3.0   # average cloned sales per retailer at risk 1.0
HIGH_DEMAND_BOOST = 1.5     # high-demand drugs are counterfeited more often
P_DIVERT_BATCH = 0.15       # share of batches that leak a few packs off the books

# Harmless noise (NOT counterfeits, so detection gets some false alarms)
P_DAMAGED = 0.008           # per shipment: one pack damaged/lost in transit
P_LOT_LOSS = 0.04           # per lot: slightly less weight received than sent

# Consumer QR scans (MongoDB scan_logs)
P_SCAN = 0.30               # share of sold packs the buyer scans
P_RESCAN = 0.08             # share of those scanned again (same buyer, same city)
P_SCAN_CLONE = 0.85         # cloned packs: both buyers scan
P_SCAN_FAKE = 0.50          # fake packs that reached a pharmacy get scanned

rng = random.Random(SEED)

# =====================================================================
# 2. REFERENCE DATA
# =====================================================================
CITIES = {  # city: (state, code, latitude, longitude)
    "Mumbai": ("Maharashtra", "MH", 19.0760, 72.8777),
    "Pune": ("Maharashtra", "MH", 18.5204, 73.8567),
    "Nagpur": ("Maharashtra", "MH", 21.1458, 79.0882),
    "Ahmedabad": ("Gujarat", "GJ", 23.0225, 72.5714),
    "Vadodara": ("Gujarat", "GJ", 22.3072, 73.1812),
    "Surat": ("Gujarat", "GJ", 21.1702, 72.8311),
    "Bengaluru": ("Karnataka", "KA", 12.9716, 77.5946),
    "Mysuru": ("Karnataka", "KA", 12.2958, 76.6394),
    "Hubballi": ("Karnataka", "KA", 15.3647, 75.1240),
    "Chennai": ("Tamil Nadu", "TN", 13.0827, 80.2707),
    "Coimbatore": ("Tamil Nadu", "TN", 11.0168, 76.9558),
    "Madurai": ("Tamil Nadu", "TN", 9.9252, 78.1198),
    "Hyderabad": ("Telangana", "TG", 17.3850, 78.4867),
    "Warangal": ("Telangana", "TG", 17.9689, 79.5941),
    "Visakhapatnam": ("Andhra Pradesh", "AP", 17.6868, 83.2185),
    "Vijayawada": ("Andhra Pradesh", "AP", 16.5062, 80.6480),
    "Delhi": ("Delhi", "DL", 28.6139, 77.2090),
    "Lucknow": ("Uttar Pradesh", "UP", 26.8467, 80.9462),
    "Kanpur": ("Uttar Pradesh", "UP", 26.4499, 80.3319),
    "Noida": ("Uttar Pradesh", "UP", 28.5355, 77.3910),
    "Kolkata": ("West Bengal", "WB", 22.5726, 88.3639),
    "Howrah": ("West Bengal", "WB", 22.5958, 88.2636),
    "Jaipur": ("Rajasthan", "RJ", 26.9124, 75.7873),
    "Udaipur": ("Rajasthan", "RJ", 24.5854, 73.7125),
    "Indore": ("Madhya Pradesh", "MP", 22.7196, 75.8577),
    "Bhopal": ("Madhya Pradesh", "MP", 23.2599, 77.4126),
    "Kochi": ("Kerala", "KL", 9.9312, 76.2673),
    "Thiruvananthapuram": ("Kerala", "KL", 8.5241, 76.9366),
    "Baddi": ("Himachal Pradesh", "HP", 30.9578, 76.7914),
}
RETAIL_CITIES = [c for c in CITIES if c != "Baddi"]

SUPPLIERS = [  # name, city, lot-number prefix
    ("Kaveri Fine Chemicals", "Vadodara", "KFC"),       # S1: antibiotic APIs
    ("Deccan Bulk Drugs", "Hyderabad", "DBD"),          # S2: other APIs
    ("Konkan Excipients", "Mumbai", "KEX"),             # S3: excipients
    ("Godavari Pharma Materials", "Visakhapatnam", "GPM"),  # S4: excipients
]
MANUFACTURERS = [  # name, city, batch-number prefix
    ("Vardhan Life Sciences", "Baddi", "VL"),           # M1
    ("Sahyadri Healthcare", "Ahmedabad", "SH"),         # M2
    ("Nilgiri Pharmaceuticals", "Hyderabad", "NP"),     # M3
]
DISTRIBUTOR_CITIES = ["Mumbai", "Pune", "Nagpur", "Ahmedabad", "Surat", "Bengaluru", "Hubballi",
                      "Chennai", "Madurai", "Hyderabad", "Delhi", "Lucknow", "Kolkata", "Jaipur", "Indore"]
DIST_PREFIX = ["Aarav", "Bharat", "Chetak", "Disha", "Ganga", "Indus", "Jyoti", "Kiran", "Lotus",
               "Meera", "Narmada", "Pavan", "Sagar", "Tapti", "Vikas", "Yamuna", "Riddhi", "Shubh"]
DIST_SUFFIX = ["Pharma Distributors", "Medical Agencies", "Healthcare Logistics", "Drug House"]
RET_BASE = ["Shree Ganesh", "Sai Krupa", "Apna", "Jeevan", "Sanjeevani", "Arogya", "Navjeevan",
            "Dhanvantari", "Mahalaxmi", "Om Sai", "Lifeline", "Wellness", "Prakash", "Anand",
            "Swasthya", "Seva", "Mangal", "Shanti", "Sunrise", "Green Cross", "Care Plus", "Janata",
            "Vardaan", "Amrit"]
PHARMACY_KIND = ["Medicals", "Pharmacy", "Chemists", "Medical Stores"]
HOSPITAL_KIND = ["Hospital", "Multispeciality Hospital", "Nursing Home"]

# Brand names are invented; any match with a real brand is accidental.
# (generic, brand, strength, form, units/pack, pack price INR, high demand,
#  active ingredient, other materials, manufacturer index)
DRUGS = [
    ("Paracetamol", "Pyrezol 500", "500 mg", "TABLET", 10, "22.50", True,
     "Paracetamol IP", ["Maize starch", "Povidone K30", "Magnesium stearate"], 0),
    ("Amoxicillin", "Amoxivar 500", "500 mg", "CAPSULE", 10, "98.00", True,
     "Amoxicillin trihydrate IP", ["Empty hard gelatin capsules", "Magnesium stearate"], 1),
    ("Azithromycin", "Azinil 500", "500 mg", "TABLET", 3, "119.00", True,
     "Azithromycin dihydrate IP", ["Microcrystalline cellulose", "Croscarmellose sodium", "Magnesium stearate"], 1),
    ("Metformin", "Glymetra 500", "500 mg", "TABLET", 15, "38.00", False,
     "Metformin hydrochloride IP", ["Povidone K30", "Microcrystalline cellulose", "Magnesium stearate"], 0),
    ("Atorvastatin", "Atorvix 10", "10 mg", "TABLET", 10, "84.00", False,
     "Atorvastatin calcium IP", ["Lactose monohydrate", "Microcrystalline cellulose", "Magnesium stearate"], 2),
    ("Pantoprazole", "Pantoril IV", "40 mg/vial", "INJECTION", 1, "52.00", False,
     "Pantoprazole sodium IP", ["Edetate disodium", "Sodium hydroxide"], 2),
    ("Ceftriaxone", "Ceftrinil 1g", "1 g/vial", "INJECTION", 1, "68.00", True,
     "Ceftriaxone sodium sterile IP", ["Water for injection"], 1),
    ("Cetirizine", "Allerzest 10", "10 mg", "TABLET", 10, "19.00", False,
     "Cetirizine hydrochloride IP", ["Lactose monohydrate", "Maize starch", "Magnesium stearate"], 0),
    ("Amlodipine", "Amlovarn 5", "5 mg", "TABLET", 15, "34.00", False,
     "Amlodipine besylate IP", ["Microcrystalline cellulose", "Dibasic calcium phosphate", "Magnesium stearate"], 0),
    ("Ibuprofen", "Ibunil Kids", "100 mg/5 ml", "SYRUP", 1, "46.00", False,
     "Ibuprofen IP", ["Sucrose", "Sorbitol solution", "Sodium benzoate"], 2),
]
API_SUPPLIER = {  # active ingredient -> supplier index
    "Amoxicillin trihydrate IP": 0, "Azithromycin dihydrate IP": 0, "Ceftriaxone sodium sterile IP": 0,
    "Paracetamol IP": 1, "Metformin hydrochloride IP": 1, "Atorvastatin calcium IP": 1,
    "Pantoprazole sodium IP": 1, "Cetirizine hydrochloride IP": 1, "Amlodipine besylate IP": 1,
    "Ibuprofen IP": 1,
}
EXCIPIENT_SUPPLIERS = [2, 3]   # any excipient can come from S3 or S4
SHELF_LIFE_MONTHS = {"TABLET": 36, "CAPSULE": 36, "INJECTION": 24, "SYRUP": 18}
SERIAL_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no 0/O, 1/I lookalikes

# =====================================================================
# 3. SMALL HELPERS
# =====================================================================
def random_date(lo, hi):
    return lo + timedelta(days=rng.randint(0, (hi - lo).days))


def add_years(d, n):
    try:
        return d.replace(year=d.year + n)
    except ValueError:              # 29 February
        return d.replace(year=d.year + n, day=28)


def add_months(d, n):
    m = d.month - 1 + n
    y, m = d.year + m // 12, m % 12 + 1
    return date(y, m, min(d.day, 28))


def day_time(d):
    """A random business-hours time (09:00-19:59) on day d."""
    return datetime(d.year, d.month, d.day, rng.randint(9, 19), rng.randint(0, 59), rng.randint(0, 59))


def biz(t):
    """Move a time forward into business hours (never backward)."""
    t = t.replace(microsecond=0)
    if t.hour < 9:
        t = t.replace(hour=9, minute=rng.randint(0, 59), second=rng.randint(0, 59))
    elif t.hour >= 20:
        t = (t + timedelta(days=1)).replace(hour=9, minute=rng.randint(0, 59), second=rng.randint(0, 59))
    return t


def km(a, b):
    """Straight-line distance between two participants (haversine)."""
    la1, lo1, la2, lo2 = map(math.radians, (float(a["lat"]), float(a["lon"]), float(b["lat"]), float(b["lon"])))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def poisson(lam):
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def kg(x):
    return Decimal(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def gtin13(first12):
    s = sum(int(c) * (3 if i % 2 else 1) for i, c in enumerate(first12))
    return first12 + str((10 - s % 10) % 10)


def canon(*values):
    """Canonical string for hashing (same rules as MySQL CONCAT + IFNULL)."""
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


def sha256(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def sql(v):
    """Python value -> SQL literal."""
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (int, Decimal)):
        return str(v)
    if isinstance(v, datetime):
        return "'" + v.strftime("%Y-%m-%d %H:%M:%S") + "'"
    if isinstance(v, date):
        return "'" + v.strftime("%Y-%m-%d") + "'"
    return "'" + str(v).replace("\\", "\\\\").replace("'", "''") + "'"


# =====================================================================
# 4. OBJECTS
# =====================================================================
class Link:
    __slots__ = ("id", "frm", "to", "stage", "risk")

    def __init__(self, frm, to, stage):
        self.frm, self.to, self.stage, self.risk, self.id = frm, to, stage, 0.0, None


class Lot:
    __slots__ = ("id", "seq", "lot_no", "material", "sent", "received", "supplier", "manufacturer",
                 "rdate", "coa", "uses_left", "hash")


class Batch:
    __slots__ = ("id", "drug", "manufacturer", "batch_no", "mfg_date", "expiry", "lots", "serials", "hash", "mseq")


class Shipment:
    __slots__ = ("id", "seq", "link", "ship_time", "receive_time", "items", "received", "fakes", "is_sale")

    def __init__(self, seq, link, ship_time, is_sale=False):
        self.seq, self.link, self.ship_time, self.is_sale = seq, link, ship_time, is_sale
        self.receive_time, self.items, self.received, self.fakes, self.id = None, [], set(), [], None

    @property
    def status(self):
        if self.receive_time is None:
            return "DISPATCHED"
        if self.fakes or len(self.received) < len(self.items):
            return "PARTIAL"
        return "RECEIVED"


class Event:
    __slots__ = ("id", "seq", "serial", "etype", "shipment", "time", "holder", "hash")
    RANK = {"MANUFACTURED": 0, "DISPATCHED": 1, "RECEIVED": 2, "SOLD": 3, "RECALLED": 4}

    def sort_key(self):
        return (self.time, self.RANK[self.etype], self.seq)

    def parties(self):
        if self.shipment is None:
            return self.holder["id"], self.holder["id"]
        return self.shipment.link.frm["id"], self.shipment.link.to["id"]


# =====================================================================
# 5. THE WORLD
# =====================================================================
class World:
    def __init__(self):
        self.participants, self.by_code = [], {}
        self.suppliers, self.manufacturers, self.distributors, self.retailers = [], [], [], []
        self.consumer = None
        self.bad_actors = []
        self.episodes = {}           # participant id -> [(start, end)]
        self.drugs = []
        self.links, self.link_by_pair = [], {}
        self.retailer_dists = {}     # retailer id -> [distributor, ...] (primary first)
        self.lots, self.open_lots, self.lot_seq = [], {}, {}
        self.batches = []
        self.pack_batch = {}         # serial -> Batch
        self.shipments, self.events = [], []
        self.injections = []
        self.sales = []              # (serial, retailer, time, high_demand)
        self.fakes_at_retailer = []  # (fake serial, retailer, time received)
        self.clones = []             # (serial, original retailer, original time, clone retailer, clone time)
        self.diverted = []           # [serial, available_from, manufacturer] leaked packs
        self.used_serials = set()
        self.seq = 0

    # ----- small factories -----
    def next_seq(self):
        self.seq += 1
        return self.seq

    def new_serial(self):
        while True:
            s = "".join(rng.choice(SERIAL_ALPHABET) for _ in range(12))
            if s not in self.used_serials:
                self.used_serials.add(s)
                return s

    def event(self, serial, etype, t, shipment=None, holder=None):
        e = Event()
        e.id, e.hash, e.seq = None, None, self.next_seq()
        e.serial, e.etype, e.time, e.shipment, e.holder = serial, etype, t, shipment, holder
        self.events.append(e)
        return e

    def shipment(self, link, ship_time, is_sale=False):
        s = Shipment(self.next_seq(), link, ship_time, is_sale)
        self.shipments.append(s)
        return s

    def inject(self, scenario, at, link=None, shipment=None, serial=None, lot=None, event=None):
        self.injections.append(dict(scenario=scenario, at=at, link=link, shipment=shipment,
                                    serial=serial, lot=lot, event=event))

    def suspended(self, p, t):
        return any(s <= t < e for s, e in self.episodes.get(p["id"], []))

    def suspension_end(self, p, t):
        for s, e in self.episodes.get(p["id"], []):
            if s <= t < e:
                return e
        return None


# =====================================================================
# 6. PARTICIPANTS, LICENSES, SUSPENSIONS
# =====================================================================
def build_participants(w):
    used_names, used_licenses = set(), set()

    def add(ptype, code, name, city=None, issue=None):
        p = {"id": len(w.participants) + 1, "code": code, "name": name, "type": ptype,
             "license_no": None, "status": None, "issue": None, "valid_till": None,
             "city": None, "state": None, "scode": None, "lat": None, "lon": None}
        if ptype != "CONSUMER":
            state, scode, lat, lon = CITIES[city]
            p.update(status="ACTIVE", issue=issue, valid_till=add_years(issue, 5), city=city,
                     state=state, scode=scode,
                     lat=Decimal(f"{lat + rng.uniform(-0.03, 0.03):.6f}"),
                     lon=Decimal(f"{lon + rng.uniform(-0.03, 0.03):.6f}"))
            tcode = {"SUPPLIER": "SUP", "MANUFACTURER": "MFG", "DISTRIBUTOR": "WHL", "RETAILER": "RET"}[ptype]
            while True:
                lic = f"{scode}-{tcode}-{issue.year}-{rng.randint(10000, 99999)}"
                if lic not in used_licenses:
                    used_licenses.add(lic)
                    p["license_no"] = lic
                    break
        w.participants.append(p)
        w.by_code[code] = p
        return p

    def old_issue():
        return random_date(date(2021, 10, 1), date(2024, 12, 31))

    def any_issue():
        return random_date(NEW_LICENSE_SINCE, date(2025, 11, 30)) if rng.random() < 0.25 else old_issue()

    for i, (name, city, _) in enumerate(SUPPLIERS):
        w.suppliers.append(add("SUPPLIER", f"S{i+1}", name, city,
                               random_date(date(2021, 10, 1), date(2024, 6, 30))))
    for i, (name, city, _) in enumerate(MANUFACTURERS):
        w.manufacturers.append(add("MANUFACTURER", f"M{i+1}", name, city,
                                   random_date(date(2021, 10, 1), date(2023, 12, 31))))

    prefixes = rng.sample(DIST_PREFIX, N_DISTRIBUTORS)
    for i, city in enumerate(DISTRIBUTOR_CITIES[:N_DISTRIBUTORS]):
        name = f"{prefixes[i]} {rng.choice(DIST_SUFFIX)}"
        w.distributors.append(add("DISTRIBUTOR", f"D{i+1}", name, city, any_issue()))

    for i in range(N_RETAILERS):
        city = rng.choice(RETAIL_CITIES)
        kind = rng.choice(HOSPITAL_KIND) if rng.random() < 0.15 else rng.choice(PHARMACY_KIND)
        name = f"{rng.choice(RET_BASE)} {kind}"
        if name in used_names:
            name = f"{name} {city}"
        used_names.add(name)
        w.retailers.append(add("RETAILER", f"R{i+1}", name, city, any_issue()))

    w.consumer = add("CONSUMER", "CONSUMER", "CONSUMER")

    # Two "bad actor" distributors: one old license, one brand new.
    ba1, ba2 = rng.sample(w.distributors, 2)
    ba1["issue"] = random_date(date(2022, 1, 1), date(2023, 12, 31))
    ba2["issue"] = random_date(date(2025, 2, 1), date(2025, 9, 30))
    for p in (ba1, ba2):
        p["valid_till"] = add_years(p["issue"], 5)
    w.bad_actors = [ba1, ba2]


def build_suspensions(w):
    """license_history comes from these episodes: ACTIVE->SUSPENDED, later SUSPENDED->ACTIVE."""
    ba1, ba2 = w.bad_actors

    def episode(p, lo, hi, lmin, lmax):
        start = datetime.combine(random_date(lo, hi), time(rng.randint(10, 16), rng.randint(0, 59)))
        end = start + timedelta(days=rng.randint(lmin, lmax), hours=rng.randint(0, 5))
        w.episodes.setdefault(p["id"], []).append((start, end))

    def past(p):  # before the simulation starts (AI "past suspensions" feature)
        episode(p, p["issue"] + timedelta(days=60), date(2025, 11, 1), 14, 55)

    old = lambda p: p["issue"] <= date(2025, 6, 30)
    past(ba1)
    for p in rng.sample([d for d in w.distributors if d not in (ba1, ba2) and old(d)], 3):
        past(p)
    for p in rng.sample([r for r in w.retailers if old(r)], 3):
        past(p)

    # During the simulation (all restored before Sep 30, so every license is ACTIVE at the end)
    episode(ba1, date(2026, 2, 10), date(2026, 2, 25), 35, 45)
    episode(ba2, date(2026, 8, 1), date(2026, 8, 10), 30, 38)
    episode(rng.choice([d for d in w.distributors if d not in (ba1, ba2)]),
            date(2026, 5, 1), date(2026, 5, 10), 20, 30)
    episode(w.suppliers[3], date(2026, 6, 1), date(2026, 6, 8), 35, 45)
    for eps in w.episodes.values():
        eps.sort()


# =====================================================================
# 7. LINKS AND THEIR HIDDEN RISK
# =====================================================================
def build_links(w):
    def add(a, b, stage):
        l = Link(a, b, stage)
        w.links.append(l)
        w.link_by_pair[(a["id"], b["id"])] = l
        return l

    S, M, D, R = w.suppliers, w.manufacturers, w.distributors, w.retailers

    # S_M: who supplies whom follows the materials each factory needs
    for si, s in enumerate(S):
        for mi, m in enumerate(M):
            needs = {API_SUPPLIER[d[7]] for d in DRUGS if d[9] == mi} | set(EXCIPIENT_SUPPLIERS)
            if si in needs:
                add(s, m, "S_M")

    # M_D: every distributor gets at least one manufacturer, plus 2-3 extra pairs each
    serve = {m["id"]: set() for m in M}
    order = D[:]
    rng.shuffle(order)
    for i, d in enumerate(order):
        serve[M[i % len(M)]["id"]].add(d["id"])
    for m in M:
        extra = [d for d in D if d["id"] not in serve[m["id"]]]
        for d in rng.sample(extra, rng.randint(2, 3)):
            serve[m["id"]].add(d["id"])
    for m in M:
        for d in D:
            if d["id"] in serve[m["id"]]:
                add(m, d, "M_D")

    # D_R: nearest distributor, often the second nearest, sometimes a far one
    for r in R:
        near = sorted(D, key=lambda d: km(r, d))
        chosen = [near[0]]
        if rng.random() < 0.6:
            chosen.append(near[1])
        if rng.random() < 0.2:
            chosen.append(rng.choice([d for d in D if d not in chosen]))
        w.retailer_dists[r["id"]] = chosen
    for d in D:
        if not any(d in v for v in w.retailer_dists.values()):
            for r in sorted(R, key=lambda r: km(r, d))[:2]:
                w.retailer_dists[r["id"]].append(d)
    for d in D:
        for r in R:
            if d in w.retailer_dists[r["id"]]:
                add(d, r, "D_R")

    # R_E: every retailer sells to the single CONSUMER row
    for r in R:
        add(r, w.consumer, "R_E")


def assign_risk(w):
    """Hidden risk per link (never stored). Built from traits the AI can see
    (cross-state, license age, past suspensions) plus bad actors, which the AI
    can only notice through behaviour (flags, mismatches) in Jan-Jun."""
    bad = {p["id"] for p in w.bad_actors}
    new = lambda p: p["issue"] is not None and p["issue"] >= NEW_LICENSE_SINCE
    past = lambda p: any(e < START for _, e in w.episodes.get(p["id"], []))
    for l in w.links:
        a, b = l.frm, l.to
        if l.stage == "R_E":
            dists = w.retailer_dists[a["id"]]
            r = (0.08 + 0.12 * new(a) + 0.18 * past(a)
                 + 0.15 * any(d["state"] != a["state"] for d in dists)
                 + 0.40 * any(d["id"] in bad for d in dists))
        else:
            r = (0.08 + 0.15 * (a["state"] != b["state"]) + 0.12 * (new(a) or new(b))
                 + 0.18 * (past(a) or past(b)) + 0.45 * (a["id"] in bad or b["id"] in bad))
        l.risk = min(1.0, max(0.02, r + rng.gauss(0, 0.06)))


# =====================================================================
# 8. DRUGS AND PRODUCTION (lots, batches, packs)
# =====================================================================
def build_drugs(w):
    used = set()
    for i, d in enumerate(DRUGS):
        while True:
            g = gtin13("890" + "".join(str(rng.randint(0, 9)) for _ in range(9)))
            if g not in used:
                used.add(g)
                break
        w.drugs.append({"id": i + 1, "generic": d[0], "brand": d[1], "strength": d[2], "form": d[3],
                        "units": d[4], "price": Decimal(d[5]), "hd": d[6], "api": d[7],
                        "excipients": d[8], "maker": w.manufacturers[d[9]], "gtin": g})


def get_lot(w, m, material, is_api, mfg_date):
    """Reuse an open lot of this material at this factory, or receive a new one."""
    for lot in w.open_lots.get((m["id"], material), []):
        if lot.uses_left > 0 and lot.rdate <= mfg_date - timedelta(days=2) and (mfg_date - lot.rdate).days <= 150:
            lot.uses_left -= 1
            return lot

    rdate = max(START.date() + timedelta(days=1), mfg_date - timedelta(days=rng.randint(3, 25)))
    at = datetime.combine(rdate, time(10, 0))
    if is_api:
        supplier = w.suppliers[API_SUPPLIER[material]]
    else:
        supplier = w.suppliers[rng.choice(EXCIPIENT_SUPPLIERS)]
    link = w.link_by_pair[(supplier["id"], m["id"])]

    fake = None
    if w.suspended(supplier, at):
        if rng.random() < P_SHIP_TO_SUSPENDED * (0.5 + link.risk):
            fake = "SUSPENDED_SUPPLIER"
        else:  # factory buys from the other excipient supplier instead
            other = [w.suppliers[i] for i in EXCIPIENT_SUPPLIERS if w.suppliers[i] is not supplier]
            if not is_api and other:
                supplier = other[0]
                link = w.link_by_pair[(supplier["id"], m["id"])]
            else:
                fake = "SUSPENDED_SUPPLIER"

    lo, hi = (150, 900) if is_api else (50, 300) if "capsules" in material else \
             (500, 3000) if "Water" in material else (100, 1500)
    sent = kg(rng.randint(lo, hi) + rng.choice([0, 0.5]))
    lot = Lot()
    lot.id, lot.hash, lot.material, lot.supplier, lot.manufacturer = None, None, material, supplier, m
    lot.rdate, lot.sent, lot.received, lot.coa = rdate, sent, sent, True
    lot.uses_left = rng.randint(1, 4) - 1
    prefix = SUPPLIERS[w.suppliers.index(supplier)][2]
    w.lot_seq[prefix] = w.lot_seq.get(prefix, 0) + 1
    lot.lot_no = f"{prefix}-{rdate:%y%m}-{w.lot_seq[prefix]:04d}"
    lot.seq = w.next_seq()

    if fake is None and rng.random() < P_FAKE_LOT * link.risk:
        fake = rng.choice(["COA_NOT_VERIFIED", "OVERWEIGHT"])
    if fake == "COA_NOT_VERIFIED":
        lot.coa = False
    elif fake == "OVERWEIGHT":
        lot.received = kg(float(sent) * rng.uniform(1.03, 1.10))
    elif fake is None and rng.random() < P_LOT_LOSS:     # harmless noise
        lot.received = kg(float(sent) * rng.uniform(0.985, 0.997))
    if fake:
        w.inject("FAKE_MATERIAL", at, link=link, lot=lot)

    w.lots.append(lot)
    w.open_lots.setdefault((m["id"], material), []).append(lot)
    return lot


def schedule_batches(w):
    plan = []
    span = (LAST_BATCH_DAY - FIRST_BATCH_DAY).days
    for mi, m in enumerate(w.manufacturers):
        mine = [d for d in w.drugs if d["maker"] is m]
        weights = [HIGH_DEMAND_BOOST if d["hd"] else 1.0 for d in mine]
        for k in range(BATCHES_PER_MANUFACTURER):
            day = FIRST_BATCH_DAY + timedelta(days=round(k * span / (BATCHES_PER_MANUFACTURER - 1)) + rng.randint(-2, 2))
            day = min(max(day, FIRST_BATCH_DAY), LAST_BATCH_DAY)
            plan.append((day, mi, k, rng.choices(mine, weights)[0]))
    plan.sort(key=lambda x: (x[0], x[1], x[2]))
    return plan


def make_batch(w, day, m, drug, mseq):
    b = Batch()
    b.id, b.hash, b.drug, b.manufacturer, b.mfg_date, b.mseq = None, None, drug, m, day, mseq
    b.expiry = add_months(day, SHELF_LIFE_MONTHS[drug["form"]])
    b.batch_no = f"{MANUFACTURERS[w.manufacturers.index(m)][2]}{day:%y%m}-{mseq:03d}"
    b.lots = [get_lot(w, m, drug["api"], True, day)] + [get_lot(w, m, x, False, day) for x in drug["excipients"]]
    b.serials = [w.new_serial() for _ in range(rng.randint(*PACKS_PER_BATCH))]
    made = datetime.combine(day, time(10, 0))
    for i, s in enumerate(b.serials):
        w.pack_batch[s] = b
        w.event(s, "MANUFACTURED", made + timedelta(seconds=4 * i), holder=m)
    w.batches.append(b)
    return b


# =====================================================================
# 9. DISTRIBUTION AND SALES (with counterfeit injection)
# =====================================================================
def dispatch(w, link, serials, ship_time):
    sh = w.shipment(link, ship_time)
    sh.items = list(serials)
    return sh, {s: w.event(s, "DISPATCHED", ship_time, shipment=sh) for s in serials}


def ship_from_manufacturer(w, b):
    m, hd = b.manufacturer, (HIGH_DEMAND_BOOST if b.drug["hd"] else 1.0)
    serials = b.serials[:]
    rng.shuffle(serials)
    release = datetime.combine(b.mfg_date, time(10, 0)) + timedelta(days=rng.randint(2, 5))
    if rng.random() < P_DIVERT_BATCH:          # a few packs leak off the books
        k = rng.randint(5, 10)
        for s in serials[:k]:
            w.diverted.append([s, release, m])
        serials = serials[k:]

    my_dists = [l.to for l in w.links if l.stage == "M_D" and l.frm is m]
    while serials:
        n = rng.randint(*MD_SHIPMENT_SIZE)
        if len(serials) - n < 60:
            n = len(serials)
        chunk, serials = serials[:n], serials[n:]
        ship = day_time((release + timedelta(days=rng.randint(0, 12))).date())
        if ship > END:
            continue                            # packs stay at the factory

        d = rng.choice(my_dists)
        link = w.link_by_pair[(m["id"], d["id"])]
        recv = biz(ship + timedelta(hours=km(m, d) / 45 + rng.uniform(6, 30)))
        unlicensed = False
        if w.suspended(d, ship) or (recv <= END and w.suspended(d, recv)):
            if rng.random() < P_SHIP_TO_SUSPENDED * (0.5 + link.risk):
                unlicensed = True
            else:
                ok = [x for x in my_dists if not w.suspended(x, ship)
                      and not w.suspended(x, ship + timedelta(days=4))]
                d = rng.choice(ok)
                link = w.link_by_pair[(m["id"], d["id"])]
                recv = biz(ship + timedelta(hours=km(m, d) / 45 + rng.uniform(6, 30)))

        sh, disp = dispatch(w, link, chunk, ship)
        if recv > END:                          # still on the road on Sep 30
            if unlicensed:
                for s in chunk:
                    w.inject("UNLICENSED_HANDLER", ship, link=link, shipment=sh, serial=s, event=disp[s])
            continue
        sh.receive_time = recv

        removed, fakes = set(), []
        if not unlicensed and rng.random() < P_SWAP * link.risk * hd:
            k = rng.randint(2, max(2, min(8, len(chunk) // 15)))
            removed = set(rng.sample(chunk, k))
            fakes = [w.new_serial() for _ in range(k)]
        elif rng.random() < P_DAMAGED:
            removed = {rng.choice(chunk)}       # harmless: damaged in transit

        arrived = []
        for s in chunk:
            if s in removed:
                if fakes:
                    w.inject("TRANSIT_SWAP", recv, link=link, shipment=sh, serial=s, event=disp[s])
                continue
            sh.received.add(s)
            e = w.event(s, "RECEIVED", recv, shipment=sh)
            arrived.append(s)
            if unlicensed:
                w.inject("UNLICENSED_HANDLER", recv, link=link, shipment=sh, serial=s, event=e)
        for f in fakes:
            sh.fakes.append(f)
            e = w.event(f, "RECEIVED", recv, shipment=sh)
            w.inject("TRANSIT_SWAP", recv, link=link, shipment=sh, serial=f, event=e)

        ship_from_distributor(w, d, arrived, recv, b)


def ship_from_distributor(w, d, serials, arrived_at, b):
    hd = HIGH_DEMAND_BOOST if b.drug["hd"] else 1.0
    my_retailers = [r for r in w.retailers if d in w.retailer_dists[r["id"]]]
    weights = [3 if w.retailer_dists[r["id"]][0] is d else 1 for r in my_retailers]
    serials = serials[:]
    rng.shuffle(serials)
    while serials:
        n = min(rng.randint(*DR_SHIPMENT_SIZE), len(serials))
        chunk, serials = serials[:n], serials[n:]
        ship = day_time((arrived_at + timedelta(days=rng.randint(1, 35))).date())
        end = w.suspension_end(d, ship)
        if end:                                  # a suspended distributor cannot dispatch
            ship = day_time((end + timedelta(days=rng.randint(1, 3))).date())
        if ship > END:
            continue                             # stays in the warehouse
        r = rng.choices(my_retailers, weights)[0]
        link = w.link_by_pair[(d["id"], r["id"])]

        skipped = []
        if rng.random() < P_STAGE_SKIP * link.risk:
            pool = [x for x in w.diverted if x[1] <= ship - timedelta(days=3)]
            if pool:
                skipped = [x[0] for x in rng.sample(pool, min(len(pool), rng.randint(3, 8)))]
                w.diverted = [x for x in w.diverted if x[0] not in set(skipped)]

        sh, disp = dispatch(w, link, chunk + skipped, ship)
        for s in skipped:
            w.inject("STAGE_SKIPPED", ship, link=link, shipment=sh, serial=s, event=disp[s])
        recv = biz(ship + timedelta(hours=km(d, r) / 45 + rng.uniform(2, 12)))
        if recv > END:
            continue
        sh.receive_time = recv

        removed, fakes, scenario = set(), [], None
        if not skipped:
            if rng.random() < P_SWAP * link.risk * hd:
                k = rng.randint(2, max(2, min(6, len(chunk) // 4)))
                removed, scenario = set(rng.sample(chunk, k)), "TRANSIT_SWAP"
                fakes = [w.new_serial() for _ in range(k)]
            elif rng.random() < P_INVENTED * link.risk * hd:
                scenario = "INVENTED_SERIAL"
                fakes = [w.new_serial() for _ in range(rng.randint(2, 6))]
            elif rng.random() < P_DAMAGED:
                removed = {rng.choice(chunk)}

        for s in chunk + skipped:
            if s in removed:
                if scenario:
                    w.inject(scenario, recv, link=link, shipment=sh, serial=s, event=disp[s])
                continue
            sh.received.add(s)
            w.event(s, "RECEIVED", recv, shipment=sh)
            sell(w, r, s, recv, b)
        for f in fakes:
            sh.fakes.append(f)
            e = w.event(f, "RECEIVED", recv, shipment=sh)
            w.inject(scenario, recv, link=link, shipment=sh, serial=f, event=e)
            w.fakes_at_retailer.append((f, r, recv))


def sell(w, r, serial, received_at, b):
    t = biz(received_at + timedelta(days=rng.expovariate(1 / SALE_DELAY_MEAN_DAYS), hours=1))
    if t > END:
        return                                   # still on the shelf
    link = w.link_by_pair[(r["id"], w.consumer["id"])]
    sh = w.shipment(link, t, is_sale=True)
    sh.items, sh.receive_time = [serial], t
    sh.received.add(serial)
    w.event(serial, "SOLD", t, shipment=sh)
    w.sales.append((serial, r, t, b.drug["hd"]))


def make_clones(w):
    """A retailer sells copies of a real serial that was already sold far away."""
    usable = [s for s in w.sales if s[2] + timedelta(days=5) <= END]
    for l in [l for l in w.links if l.stage == "R_E"]:
        cloner = l.frm
        done = set()
        for _ in range(poisson(CLONES_PER_RETAILER * l.risk)):
            for _try in range(60):
                a, b2 = rng.choice(usable), rng.choice(usable)
                orig = b2 if (b2[3] and not a[3]) else a          # prefer high-demand drugs
                if orig[1] is not cloner and orig[0] not in done and km(orig[1], cloner) > 300:
                    break
            else:
                continue
            t = biz(orig[2] + timedelta(hours=rng.uniform(3, 96)))
            if t > END:
                continue
            done.add(orig[0])
            sh = w.shipment(l, t, is_sale=True)
            sh.items, sh.receive_time = [orig[0]], t
            sh.received.add(orig[0])
            e = w.event(orig[0], "SOLD", t, shipment=sh)
            w.inject("CLONED_SERIAL", t, link=l, shipment=sh, serial=orig[0], event=e)
            w.clones.append((orig[0], orig[1], orig[2], cloner, t))


# =====================================================================
# 10. IDS, HASHES, PACK STATE
# =====================================================================
def assign_ids_and_hashes(w):
    for i, l in enumerate(w.links, 1):
        l.id = i
    w.lots.sort(key=lambda x: (x.rdate, x.seq))
    for i, lot in enumerate(w.lots, 1):
        lot.id = i
    for lot in w.lots:
        lot.hash = sha256(canon(lot.id, lot.lot_no, lot.material, lot.sent, lot.received,
                                lot.supplier["id"], lot.manufacturer["id"], lot.rdate, lot.coa))
    w.batches.sort(key=lambda b: (b.mfg_date, b.manufacturer["id"], b.mseq))
    for i, b in enumerate(w.batches, 1):
        b.id = i
        lot_ids = ",".join(str(x) for x in sorted({lot.id for lot in b.lots}))
        b.hash = sha256(canon(b.id, b.drug["id"], b.manufacturer["id"], b.batch_no, b.mfg_date,
                              b.expiry, len(b.serials), lot_ids))
    w.shipments.sort(key=lambda s: (s.ship_time, s.seq))
    for i, s in enumerate(w.shipments, 1):
        s.id = i
    w.events.sort(key=Event.sort_key)
    for i, e in enumerate(w.events, 1):
        e.id = i
        frm, to = e.parties()
        e.hash = sha256(canon(e.id, e.serial, e.etype, frm, to,
                              e.shipment.id if e.shipment else None, e.time))


def pack_states(w):
    """current_owner and status = what the pack's latest event says."""
    last = {}
    for e in w.events:                     # already in time order
        if e.serial in w.pack_batch:
            last[e.serial] = e
    state = {}
    for s, e in last.items():
        if e.etype == "MANUFACTURED":
            state[s] = (e.holder, "IN_STOCK")
        elif e.etype == "DISPATCHED":
            state[s] = (e.shipment.link.frm, "IN_TRANSIT")
        elif e.etype == "RECEIVED":
            state[s] = (e.shipment.link.to, "IN_STOCK")
        else:
            state[s] = (w.consumer, "SOLD")
    return state


# =====================================================================
# 11. CONSUMER SCANS (MongoDB scan_logs)
# =====================================================================
def build_scans(w):
    scans = []

    def scan(serial, place, t):
        if t > END:
            return
        utc = t - timedelta(hours=5, minutes=30)             # SQL times are India time
        scans.append({
            "serial_no": serial,
            "scanned_at": {"$date": utc.strftime("%Y-%m-%dT%H:%M:%SZ")},
            "city": place["city"],
            "lat": round(float(place["lat"]) + rng.uniform(-0.04, 0.04), 4),
            "lon": round(float(place["lon"]) + rng.uniform(-0.04, 0.04), 4),
            "device": {"os": rng.choice(["Android", "Android", "Android", "iOS"]),
                       "app_version": rng.choice(["1.0", "1.1", "1.2"])},
            "verdict": None,      # filled by the verification step, not by the generator
            "reasons": [],
        })

    cloned = {c[0]: c for c in w.clones}
    for serial, r, t, _ in w.sales:
        if serial in cloned:
            continue
        if rng.random() < P_SCAN:
            first = t + timedelta(hours=rng.uniform(0.5, 72))
            scan(serial, r, first)
            if rng.random() < P_RESCAN:
                scan(serial, r, first + timedelta(days=rng.uniform(1, 10)))
    for serial, r_orig, t_orig, r_clone, t_clone in w.clones:
        if rng.random() < P_SCAN_CLONE:
            scan(serial, r_orig, t_orig + timedelta(hours=rng.uniform(0.5, 48)))
        if rng.random() < P_SCAN_CLONE:
            scan(serial, r_clone, t_clone + timedelta(hours=rng.uniform(0.5, 48)))
    for f, r, t in w.fakes_at_retailer:
        if rng.random() < P_SCAN_FAKE:
            scan(f, r, t + timedelta(days=rng.uniform(1, 25)))
    scans.sort(key=lambda x: x["scanned_at"]["$date"])
    return scans


# =====================================================================
# 12. SELF-CHECK (same rules as the schema's keys and CHECK constraints)
# =====================================================================
def self_check(w, state):
    errors = []
    err = errors.append
    types_ok = {"S_M": ("SUPPLIER", "MANUFACTURER"), "M_D": ("MANUFACTURER", "DISTRIBUTOR"),
                "D_R": ("DISTRIBUTOR", "RETAILER"), "R_E": ("RETAILER", "CONSUMER")}

    lic = [p["license_no"] for p in w.participants if p["license_no"]]
    if len(lic) != len(set(lic)):
        err("duplicate license_no")
    for p in w.participants:
        if p["issue"] and not p["valid_till"] > p["issue"]:
            err(f"license dates {p['code']}")
    for d in w.drugs:
        if len(d["gtin"]) != 13 or gtin13(d["gtin"][:12]) != d["gtin"]:
            err(f"gtin {d['id']}")
    pairs = set()
    for l in w.links:
        if (l.frm["type"], l.to["type"]) != types_ok[l.stage] or l.frm is l.to:
            err(f"link type {l.id}")
        if (l.frm["id"], l.to["id"]) in pairs:
            err(f"duplicate link {l.id}")
        pairs.add((l.frm["id"], l.to["id"]))
    lotkeys = set()
    for lot in w.lots:
        if lot.sent <= 0 or lot.received <= 0:
            err(f"lot qty {lot.id}")
        if lot.supplier["type"] != "SUPPLIER" or lot.manufacturer["type"] != "MANUFACTURER":
            err(f"lot types {lot.id}")
        if (lot.supplier["id"], lot.lot_no) in lotkeys:
            err(f"duplicate lot_no {lot.lot_no}")
        lotkeys.add((lot.supplier["id"], lot.lot_no))
        if (lot.supplier["id"], lot.manufacturer["id"]) not in w.link_by_pair:
            err(f"lot without S_M link {lot.id}")
    bkeys = set()
    for b in w.batches:
        if not b.expiry > b.mfg_date or not b.serials:
            err(f"batch dates/qty {b.id}")
        if (b.manufacturer["id"], b.batch_no) in bkeys:
            err(f"duplicate batch_no {b.batch_no}")
        bkeys.add((b.manufacturer["id"], b.batch_no))
        for lot in b.lots:
            if lot.manufacturer is not b.manufacturer or lot.rdate > b.mfg_date - timedelta(days=2):
                err(f"batch {b.id} lot {lot.id}")
    for s in w.shipments:
        if s.ship_time > END or (s.receive_time and (s.receive_time < s.ship_time or s.receive_time > END)):
            err(f"shipment times {s.id}")
        if len(set(s.items)) != len(s.items):
            err(f"duplicate item in shipment {s.id}")
        if not s.is_sale and w.suspended(s.link.frm, s.ship_time):
            err(f"suspended sender dispatched {s.id}")
        for x in s.items:
            if x not in w.pack_batch:
                err(f"shipment_item unknown serial {s.id}")
    rcv = {(e.shipment.id, e.serial) for e in w.events if e.etype in ("RECEIVED", "SOLD")}
    for s in w.shipments:
        for x in s.items:
            if ((s.id, x) in rcv) != (x in s.received):
                err(f"received flag {s.id} {x}")
    for e in w.events:
        if e.time > END or len(e.hash) != 64:
            err(f"event {e.id}")
        if (e.etype in ("MANUFACTURED", "RECALLED")) != (e.shipment is None):
            err(f"event shipment rule {e.id}")
    if len(state) != len(w.pack_batch):
        err("pack without events")
    injected = {i["serial"] for i in w.injections if i["serial"]}
    for s, (owner, status) in state.items():   # genuine packs never go backwards
        pass
    seq_ok = {"MANUFACTURED": {"DISPATCHED"}, "DISPATCHED": {"RECEIVED"},
              "RECEIVED": {"DISPATCHED", "SOLD"}, "SOLD": set()}
    last = {}
    for e in w.events:
        if e.serial not in w.pack_batch or e.serial in injected:
            continue
        prev = last.get(e.serial)
        if prev is None and e.etype != "MANUFACTURED":
            err(f"pack {e.serial} does not start with MANUFACTURED")
        if prev is not None and e.etype not in seq_ok[prev]:
            err(f"pack {e.serial}: {prev} then {e.etype}")
        last[e.serial] = e.etype
    return errors


# =====================================================================
# 13. WRITE FILES
# =====================================================================
def write_inserts(f, table, cols, rows, chunk=1000):
    head = f"INSERT INTO {table} ({', '.join(cols)}) VALUES\n"
    for i in range(0, len(rows), chunk):
        part = rows[i:i + chunk]
        f.write(head + ",\n".join("(" + ", ".join(sql(v) for v in r) + ")" for r in part) + ";\n")
    f.write("\n")


def write_sql(w, state, path):
    hist = []
    for pid, eps in sorted(w.episodes.items()):
        for s, e in eps:
            hist.append((pid, "ACTIVE", "SUSPENDED", s))
            hist.append((pid, "SUSPENDED", "ACTIVE", e))
    hist.sort(key=lambda h: (h[3], h[0]))

    with open(path, "w", encoding="utf-8") as f:
        f.write("-- =====================================================================\n")
        f.write("-- Pharma Supply Chain DBMS Project\n")
        f.write(f"-- seed_data.sql : generated by generate_data.py (seed {SEED})\n")
        f.write("-- Load:  mysql -u root -p pharma_counterfeit_db < seed_data.sql\n")
        f.write("-- One transaction: if any row fails, nothing is kept.\n")
        f.write("-- Tables must be empty first (see the optional clear block below).\n")
        f.write("-- =====================================================================\n")
        f.write("-- Participant codes used in documents and demos:\n")
        line = "--"
        for p in w.participants:
            item = f" {p['code']}={p['id']}"
            if len(line) + len(item) > 78:
                f.write(line + "\n")
                line = "--"
            line += item
        f.write(line + "\n\n")
        f.write("USE pharma_counterfeit_db;\n\n")
        f.write("-- Tells the triggers that this is the seed load, so they stay quiet.\n")
        f.write("SET @seed_loading = 1;\n\n")
        f.write("-- OPTIONAL CLEAR: remove the '-- ' to empty all tables before reloading.\n")
        for t in ["risk_factor", "link_risk_score", "injected_counterfeit", "anomaly_flag", "trace_event",
                  "shipment_item", "shipment", "link", "pack", "batch_material", "batch", "material_lot",
                  "drug", "license_history", "participant"]:
            f.write(f"-- DELETE FROM {t};\n")
        f.write("\nSTART TRANSACTION;\n\n")

        write_inserts(f, "participant",
                      ["participant_id", "name", "participant_type", "license_no", "license_status",
                       "license_issue_date", "license_valid_till", "city", "state", "latitude", "longitude"],
                      [(p["id"], p["name"], p["type"], p["license_no"], p["status"], p["issue"], p["valid_till"],
                        p["city"], p["state"], p["lat"], p["lon"]) for p in w.participants])
        write_inserts(f, "license_history", ["history_id", "participant_id", "old_status", "new_status", "changed_at"],
                      [(i, *h) for i, h in enumerate(hist, 1)])
        write_inserts(f, "drug", ["drug_id", "generic_name", "brand_name", "strength", "dosage_form",
                                  "units_per_pack", "gtin", "pack_price", "high_demand"],
                      [(d["id"], d["generic"], d["brand"], d["strength"], d["form"], d["units"], d["gtin"],
                        d["price"], d["hd"]) for d in w.drugs])
        write_inserts(f, "material_lot", ["lot_id", "lot_no", "material_name", "quantity_sent_kg",
                                          "quantity_received_kg", "supplier_id", "manufacturer_id",
                                          "received_date", "coa_verified", "lot_hash", "ledger_synced"],
                      [(x.id, x.lot_no, x.material, x.sent, x.received, x.supplier["id"], x.manufacturer["id"],
                        x.rdate, x.coa, x.hash, False) for x in w.lots])
        write_inserts(f, "batch", ["batch_id", "drug_id", "manufacturer_id", "batch_no", "mfg_date",
                                   "expiry_date", "quantity", "qc_status", "batch_hash", "ledger_synced"],
                      [(b.id, b.drug["id"], b.manufacturer["id"], b.batch_no, b.mfg_date, b.expiry,
                        len(b.serials), "APPROVED", b.hash, False) for b in w.batches])
        write_inserts(f, "batch_material", ["batch_id", "lot_id"],
                      [(b.id, lid) for b in w.batches for lid in sorted({x.id for x in b.lots})])
        write_inserts(f, "pack", ["serial_no", "batch_id", "current_owner", "status"],
                      [(s, b.id, state[s][0]["id"], state[s][1])
                       for b in w.batches for s in b.serials])
        write_inserts(f, "link", ["link_id", "from_participant", "to_participant"],
                      [(l.id, l.frm["id"], l.to["id"]) for l in w.links])
        write_inserts(f, "shipment", ["shipment_id", "link_id", "ship_time", "receive_time", "status"],
                      [(s.id, s.link.id, s.ship_time, s.receive_time, s.status) for s in w.shipments])
        write_inserts(f, "shipment_item", ["shipment_id", "serial_no", "received"],
                      [(s.id, x, x in s.received) for s in w.shipments for x in s.items])
        write_inserts(f, "trace_event", ["event_id", "serial_no", "event_type", "shipment_id", "event_time",
                                         "event_hash", "ledger_synced"],
                      [(e.id, e.serial, e.etype, e.shipment.id if e.shipment else None, e.time, e.hash, False)
                       for e in w.events])
        inj = sorted(w.injections, key=lambda i: (i["at"], i["scenario"]))
        write_inserts(f, "injected_counterfeit", ["inject_id", "scenario_type", "link_id", "shipment_id",
                                                  "serial_no", "lot_id", "event_id", "injected_at"],
                      [(n, i["scenario"], i["link"].id if i["link"] else None,
                        i["shipment"].id if i["shipment"] else None, i["serial"],
                        i["lot"].id if i["lot"] else None, i["event"].id if i["event"] else None, i["at"])
                       for n, i in enumerate(inj, 1)])
        f.write("COMMIT;\nSET @seed_loading = NULL;\n")


def write_scans(scans, path):
    with open(path, "w", encoding="utf-8") as f:
        for s in scans:
            f.write(json.dumps(s) + "\n")


# =====================================================================
# 14. SUMMARY
# =====================================================================
def summary(w, state, scans, out):
    print("\nRows per table")
    rows = {
        "participant": len(w.participants),
        "license_history": 2 * sum(len(v) for v in w.episodes.values()),
        "drug": len(w.drugs), "material_lot": len(w.lots), "batch": len(w.batches),
        "batch_material": sum(len({x.id for x in b.lots}) for b in w.batches),
        "pack": len(w.pack_batch), "link": len(w.links), "shipment": len(w.shipments),
        "shipment_item": sum(len(s.items) for s in w.shipments), "trace_event": len(w.events),
        "injected_counterfeit": len(w.injections),
    }
    for k, v in rows.items():
        print(f"  {k:22s}{v:>9,}")
    print(f"  {'scan_logs (MongoDB)':22s}{len(scans):>9,}")

    status = {}
    for _, st in state.values():
        status[st] = status.get(st, 0) + 1
    print("\nPack status on Sep 30:", ", ".join(f"{k} {v:,}" for k, v in sorted(status.items())))

    print("\nCounterfeits planted (rows / links), Jan-Jun | Jul-Sep")
    for sc in ["FAKE_MATERIAL", "INVENTED_SERIAL", "CLONED_SERIAL", "TRANSIT_SWAP",
               "UNLICENSED_HANDLER", "STAGE_SKIPPED"]:
        a = [i for i in w.injections if i["scenario"] == sc and i["at"] < LABEL_START]
        b = [i for i in w.injections if i["scenario"] == sc and i["at"] >= LABEL_START]
        la = len({i["link"].id for i in a})
        lb = len({i["link"].id for i in b})
        print(f"  {sc:20s}{len(a):>6} /{la:>3}  | {len(b):>6} /{lb:>3}")
    real_events = len(w.events)
    hit = len({i["event"].id for i in w.injections if i["event"]})
    print(f"  events touched by a counterfeit: {hit:,} of {real_events:,} ({100*hit/real_events:.1f}%)")

    print("\nAI labels: links with a counterfeit in Jul-Sep (positive / all links)")
    for st in ["S_M", "M_D", "D_R", "R_E"]:
        ls = [l for l in w.links if l.stage == st]
        pos = {i["link"].id for i in w.injections if i["at"] >= LABEL_START and i["link"] and i["link"].stage == st}
        print(f"  {st}: {len(pos):>3} / {len(ls)}")

    for name in ("seed_data.sql", "scan_logs.json"):
        p = os.path.join(out, name)
        print(f"\n{p}: {os.path.getsize(p)/1e6:.1f} MB", end="")
    print()


# =====================================================================
# MAIN
# =====================================================================
def main():
    global rng
    ap = argparse.ArgumentParser(description="Generate seed data for pharma_counterfeit_db")
    ap.add_argument("--out", default="output", help="output folder (default: output)")
    ap.add_argument("--seed", type=int, default=SEED, help=f"random seed (default: {SEED})")
    args = ap.parse_args()
    rng = random.Random(args.seed)

    w = World()
    print("Building participants, licenses and links...")
    build_participants(w)
    build_suspensions(w)
    build_links(w)
    assign_risk(w)
    build_drugs(w)

    print("Simulating production, distribution and sales...")
    mseq = {}
    for day, mi, _, drug in schedule_batches(w):
        m = w.manufacturers[mi]
        mseq[mi] = mseq.get(mi, 0) + 1
        b = make_batch(w, day, m, drug, mseq[mi])
        ship_from_manufacturer(w, b)
    make_clones(w)

    print("Numbering rows and computing hashes...")
    assign_ids_and_hashes(w)
    state = pack_states(w)
    scans = build_scans(w)

    print("Checking the data against the schema rules...")
    errors = self_check(w, state)
    if errors:
        print(f"SELF-CHECK FAILED ({len(errors)} problems). First ones:")
        for e in errors[:20]:
            print("  -", e)
        raise SystemExit(1)
    print("  all checks passed")

    os.makedirs(args.out, exist_ok=True)
    print("Writing files...")
    write_sql(w, state, os.path.join(args.out, "seed_data.sql"))
    write_scans(scans, os.path.join(args.out, "scan_logs.json"))
    summary(w, state, scans, args.out)


if __name__ == "__main__":
    main()
