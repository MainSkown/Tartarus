import json, sys, time, os
sys.path.insert(0, "/opt/CAPEv2")
os.chdir("/opt/CAPEv2")
t0 = time.monotonic()
import modules.processing.network as net
t1 = time.monotonic()
path = sys.argv[1]
net.PCAP_TYPE = net.check_pcap_file_type(path)
from lib.cuckoo.common.config import Config
cfg = Config("processing").network
opts = {"sorted": False}
ja3 = {}
res = net.Pcap(path, ja3, opts).run()
t2 = time.monotonic()
print("import %.2fs run %.2fs" % (t1 - t0, t2 - t1), file=sys.stderr)
res["pcap_sha256"] = None
json.dump(res, open(sys.argv[2], "w"), default=str)
print({k: len(v) if hasattr(v, "__len__") else v for k, v in res.items()})
