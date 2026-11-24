"""Writes targets.h for lan_probe.c from GET /api/lan-presets (the preset's own addresses, never typed in)."""
import json
import sys
import urllib.request

preset_id, out = sys.argv[1], sys.argv[2]
with urllib.request.urlopen("http://127.0.0.1:8080/api/lan-presets") as response:
    preset = next(p for p in json.load(response) if p["id"] == preset_id)
hosts = preset["hosts"]
smb_hosts = [h["address"] for h in hosts if any(s["port"] == 445 for s in h["services"])]
lines = ["/* generated from GET /api/lan-presets, preset %s */" % preset_id]
lines.append("static const struct { const char *ip; int port; } SWEEP[] = {")
for h in hosts:
    for s in h["services"]:
        lines.append('    {"%s", %d},' % (h["address"], s["port"]))
lines.append("};")
lines.append("static const char *SMB_HOSTS[] = {%s};" % ", ".join('"%s"' % a for a in smb_hosts))
open(out, "w").write("\n".join(lines) + "\n")
print(len(smb_hosts), "smb hosts;", sum(len(h["services"]) for h in hosts), "sweep targets")
