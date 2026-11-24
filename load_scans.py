from bson import json_util
from common.config import get_mongo_db

col = get_mongo_db()["scan_logs"]
col.insert_many([json_util.loads(line) for line in open("output/scan_logs.json")])
print(col.count_documents({}), "scans loaded")