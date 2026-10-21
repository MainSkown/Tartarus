"""Normalise network sections with the real CapeNetworkNormalizer and compare against the OpenSearch events of the run."""
import json, sys
from datetime import datetime, UTC
from app.ingest.cape_network import CapeNetworkNormalizer
from app.ingest.protocol import IngestContext

S = sys.argv[1]
ref_events = [h["_source"] for h in json.load(open(f"{S}/ref-net-events.json"))["hits"]["hits"]]
started = datetime(2026, 10, 21, 12, 52, 45, tzinfo=UTC)

def norm(report_path, started_at, section_only=None):
    report = json.load(open(report_path))
    if section_only: report = {"network": report["network"]}
    return list(CapeNetworkNormalizer().normalise(report, IngestContext(370, started_at)))

def key(e, with_time=False):
    d = e.get("destination", {}); s = e.get("source", {})
    k = (e["event"]["action"], e.get("network", {}).get("transport"), e.get("dns", {}).get("question", {}).get("name"),
         json.dumps(e.get("dns", {}).get("answers"), sort_keys=True), s.get("ip"), s.get("port"), d.get("ip"), d.get("port"), d.get("domain"),
         e.get("url", {}).get("full"), e.get("tartarus", {}).get("summary"))
    return k + ((e["@timestamp"],) if with_time else ())

def compare(name, a, b):
    ka = sorted(map(key, a), key=str); kb = sorted(map(key, b), key=str)
    same_t = sorted(key(e, True) for e in a) == sorted(key(e, True) for e in b)
    print(f"{name}: {len(a)} vs {len(b)} events; same fields ignoring time: {ka == kb}; same incl. timestamps: {same_t}")
    only_a = [k for k in ka if k not in kb][:3]; only_b = [k for k in kb if k not in ka][:3]
    if only_a or only_b: print("  only a:", only_a, "\n  only b:", only_b)

# sanity: re-normalising the run's own report reproduces what is in OpenSearch (apart from process attribution)
own = norm(f"{S}/ref-report.json", started)
compare("run report re-normalised vs OpenSearch of the run", ref_events, own)
imp = norm(f"{S}/pcaptask-report.json", started, section_only=True)
compare("CAPE pcap task report vs OpenSearch of the run (same started_at)", ref_events, imp)
lib = norm(f"{S}/lib-out.json", started) if False else None
# import semantics: started_at = first packet

first_packet = datetime.fromtimestamp(1792587172.871033, UTC)
lib_report = {"network": json.load(open(f"{S}/lib-out.json"))}
json.dump(lib_report, open(f"{S}/lib-report.json", "w"))
imp2 = norm(f"{S}/lib-report.json", first_packet)
compare("direct dpkt Pcap() call, started_at = first packet (import semantics)", ref_events, imp2)
compare("direct dpkt Pcap() call, started_at = run's started_at", ref_events, norm(f"{S}/lib-report.json", started))
json.dump({"network": json.load(open(f"{S}/trunc-out.json"))}, open(f"{S}/trunc-report.json", "w"))
compare("NEGATIVE CONTROL truncated pcap vs run", ref_events, norm(f"{S}/trunc-report.json", started))
import statistics
ref_t = {key(e): e["@timestamp"] for e in ref_events if e["event"]["action"] == "network-connection"}
d = [ (datetime.fromisoformat(ref_t[key(e)].replace("Z","+00:00")) - datetime.fromisoformat(e["@timestamp"].replace("Z","+00:00"))).total_seconds() for e in imp2 if e["event"]["action"]=="network-connection" and key(e) in ref_t]
print("flow timestamp shift import vs run: min %.3f max %.3f s" % (min(d), max(d)))
