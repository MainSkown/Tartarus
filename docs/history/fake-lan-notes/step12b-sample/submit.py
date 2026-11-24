"""submit.py EXE OPTIONS_JSON -> prints the response; used for step 12b."""
import json, sys, urllib.request, urllib.error, uuid
exe, options = sys.argv[1], json.loads(sys.argv[2])
b = uuid.uuid4().hex
content = open(exe, "rb").read()
data = (f'--{b}\r\nContent-Disposition: form-data; name="options"\r\n\r\n{json.dumps(options)}\r\n'.encode()
        + f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="lan_probe.exe"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode()
        + content + f"\r\n--{b}--\r\n".encode())
req = urllib.request.Request("http://127.0.0.1:8080/api/analyses", data=data, method="POST",
                             headers={"Content-Type": f"multipart/form-data; boundary={b}"})
try:
    with urllib.request.urlopen(req, timeout=60) as r:
        print(r.status, r.read().decode())
except urllib.error.HTTPError as e:
    print(e.code, e.read().decode())
