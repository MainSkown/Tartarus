import sys, collections
from datetime import datetime, UTC
from pathlib import Path
from app.ingest.volatility import VolatilityNormalizer
from app.ingest.protocol import IngestContext
ctx = IngestContext(999, datetime(2026, 10, 21, 12, 0, tzinfo=UTC), analysis_dir=Path(sys.argv[1]))
n = VolatilityNormalizer()
events = list(n.normalise({}, ctx))
print(len(events), "events; dropped:", dict(n.dropped))
for e in events:
    if e["event"]["action"] == "memory-finding" or "detection" in e["event"]["action"]:
        print(e["event"]["action"], e["event"]["severity"], e.get("process", {}).get("name"), e.get("process", {}).get("pid"), "|", e["tartarus"]["summary"][:110])
print("--- detections")
print(collections.Counter((e["event"]["action"], e["event"]["severity"], e.get("process", {}).get("name"), (e.get("rule") or {}).get("name")) for e in events if "rule" in e))
