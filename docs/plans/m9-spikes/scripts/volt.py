"""usage: volt.py DUMP PLUGIN [--pid ...]   runs vol as the cape user like memory_logic does and times it"""
import subprocess, sys, time, json, os
dump, plugin, *extra = sys.argv[1:]
cmd = ["/opt/CAPEv2/.venv/bin/vol", "-q", "--offline", "-s", "/var/lib/libvirt/tartarus/symbols", "-f", dump, "-r", "json", plugin, *extra]
t = time.monotonic()
r = subprocess.run(cmd, capture_output=True, text=True, user="cape", group="cape", extra_groups=[], env={"HOME": "/home/cape", "PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8"}, cwd="/")
dt = time.monotonic() - t
try: n = len(json.loads(r.stdout))
except Exception: n = None
print(f"{plugin} rc={r.returncode} {dt:.1f}s rows={n} stdout={len(r.stdout)}B stderr_last={r.stderr.strip().splitlines()[-1:] }")
open(f"/tmp/p9/{os.path.basename(dump)}.{plugin}.json", "w").write(r.stdout)
