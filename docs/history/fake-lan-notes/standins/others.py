"""Stand-ins for SSH, LDAP, MSSQL, WinRM and RDP. usage: others.py ADDR ssh=22 ldap=389 mssql=1433 winrm=5985 rdp=3389"""
import asyncio, base64, json, os, struct, sys, time
import asyncssh
from ntlmhelp import challenge_message, parse_authenticate, find_ntlmssp, ntlm_type, spnego_challenge

HOST_NAME, DOMAIN = "FS01", "CORP"
def log(**kw):
    kw["ts"] = round(time.time(), 3); print(json.dumps(kw), flush=True)

# ---------------- SSH ----------------
class SSHSrv(asyncssh.SSHServer):
    def connection_made(self, conn): self.peer = conn.get_extra_info("peername")[0]; log(svc="ssh", ev="connect", src=self.peer)
    def begin_auth(self, username): self.user = username; return True
    def password_auth_supported(self): return True
    def validate_password(self, username, password): log(svc="ssh", ev="login", src=self.peer, user=username, password=password); return True
    def public_key_auth_supported(self): return True
    def validate_public_key(self, username, key): log(svc="ssh", ev="pubkey", src=self.peer, user=username, fp=key.get_fingerprint()); return False
    def connection_lost(self, exc): log(svc="ssh", ev="close", src=self.peer)
async def ssh_process(process):
    log(svc="ssh", ev="exec", command=process.command, subsystem=process.subsystem)
    process.stdout.write(""); process.exit(0)
async def start_ssh(addr, port):
    key = asyncssh.generate_private_key("ssh-ed25519")
    await asyncssh.create_server(SSHSrv, addr, port, server_host_keys=[key], process_factory=ssh_process,
                                 server_version="OpenSSH_8.9p1 Ubuntu-3ubuntu0.10", line_editor=False)

# ---------------- LDAP (ldap3's ASN.1 classes) ----------------
from pyasn1.codec.ber import decoder, encoder
from ldap3.protocol.rfc4511 import (LDAPMessage, BindResponse, SearchResultEntry, SearchResultDone, ResultCode, LDAPDN,
                                    LDAPString, PartialAttributeList, PartialAttribute, AttributeDescription, Vals, AttributeValue,
                                    ProtocolOp, MessageID)
BASE_DN = "DC=corp,DC=local"
ROOT_DSE = {"defaultNamingContext": [BASE_DN], "rootDomainNamingContext": [BASE_DN], "namingContexts": [BASE_DN, "CN=Configuration," + BASE_DN],
            "dnsHostName": ["DC01.corp.local"], "serverName": ["CN=DC01,CN=Servers,CN=Default-First-Site-Name,CN=Sites,CN=Configuration," + BASE_DN],
            "supportedLDAPVersion": ["3", "2"], "domainFunctionality": ["7"], "forestFunctionality": ["7"], "domainControllerFunctionality": ["7"],
            "supportedSASLMechanisms": ["GSSAPI", "GSS-SPNEGO", "EXTERNAL", "DIGEST-MD5"], "isSynchronized": ["TRUE"], "isGlobalCatalogReady": ["TRUE"],
            "configurationNamingContext": ["CN=Configuration," + BASE_DN], "schemaNamingContext": ["CN=Schema,CN=Configuration," + BASE_DN], "ldapServiceName": ["corp.local:dc01$@CORP.LOCAL"], "highestCommittedUSN": ["12345"], "currentTime": ["20261123140000.0Z"]}
async def read_ber(reader):
    head = await reader.readexactly(2)
    n = head[1]; extra = b""
    if n & 0x80:
        extra = await reader.readexactly(n & 0x7F); n = int.from_bytes(extra, "big")
    return head + extra + await reader.readexactly(n)
def ldap_msg(mid, op_name, op):
    m = LDAPMessage(); m["messageID"] = MessageID(mid); m["protocolOp"][op_name] = op
    return encoder.encode(m)
def ldap_result(cls, code=0, diag=""):
    r = cls(); r["resultCode"] = ResultCode(code); r["matchedDN"] = LDAPDN(""); r["diagnosticMessage"] = LDAPString(diag); return r
def entry(dn, attrs):
    e = SearchResultEntry(); e["object"] = LDAPDN(dn)
    pal = PartialAttributeList()
    for i, (k, vs) in enumerate(attrs.items()):
        pa = PartialAttribute(); pa["type"] = AttributeDescription(k)
        pa["vals"] = Vals()
        for j, v in enumerate(vs): pa["vals"][j] = AttributeValue(v)
        pal[i] = pa
    e["attributes"] = pal; return e
async def ldap_conn(reader, writer):
    peer = writer.get_extra_info("peername")[0]; log(svc="ldap", ev="connect", src=peer); chal = os.urandom(8)
    try:
        while True:
            raw = await read_ber(reader)
            msg, _ = decoder.decode(raw, asn1Spec=LDAPMessage())
            mid = int(msg["messageID"]); op = msg["protocolOp"].getName()
            if op == "bindRequest":
                b = msg["protocolOp"]["bindRequest"]; auth = b["authentication"].getName()
                log(svc="ldap", ev="bind", src=peer, dn=str(b["name"]), auth=auth, password=bytes(b["authentication"]["simple"]).decode("latin1") if auth == "simple" else None)
                if auth in ("sicilyNegotiate", "sicilyResponse") or (auth == "sasl" and str(b["authentication"]["sasl"]["mechanism"]) in ("GSS-SPNEGO", "NTLM")):
                    creds = bytes(b["authentication"][auth]) if auth != "sasl" else bytes(b["authentication"]["sasl"]["credentials"])
                    blob = find_ntlmssp(creds)
                    if blob and ntlm_type(blob) == 1:
                        ch = challenge_message(HOST_NAME, DOMAIN, chal)
                        r = ldap_result(BindResponse, 14 if auth == "sasl" else 0)
                        if auth == "sasl": r["serverSaslCreds"] = spnego_challenge(ch)
                        else: r["matchedDN"] = LDAPDN(ch.decode("latin1"))
                        writer.write(ldap_msg(mid, "bindResponse", r))
                    elif blob and ntlm_type(blob) == 3:
                        log(svc="ldap", ev="ntlm", src=peer, **parse_authenticate(blob, chal))
                        writer.write(ldap_msg(mid, "bindResponse", ldap_result(BindResponse, 49, "80090308: LdapErr: DSID-0C090569, comment: AcceptSecurityContext error, data 52e, v4563")))
                    else: writer.write(ldap_msg(mid, "bindResponse", ldap_result(BindResponse, 49)))
                else:
                    writer.write(ldap_msg(mid, "bindResponse", ldap_result(BindResponse, 0)))
            elif op == "searchRequest":
                s = msg["protocolOp"]["searchRequest"]; base = str(s["baseObject"])
                log(svc="ldap", ev="search", src=peer, base=base, scope=int(s["scope"]), filter=str(s["filter"].prettyPrint())[:200])
                if base == "":
                    writer.write(ldap_msg(mid, "searchResEntry", entry("", ROOT_DSE)))
                elif base.lower() == BASE_DN.lower():
                    writer.write(ldap_msg(mid, "searchResEntry", entry(BASE_DN, {"objectClass": ["top", "domain", "domainDNS"], "dc": ["corp"], "name": ["corp"]})))
                writer.write(ldap_msg(mid, "searchResDone", ldap_result(SearchResultDone)))
            elif op == "unbindRequest": break
            else: writer.write(ldap_msg(mid, "searchResDone", ldap_result(SearchResultDone, 2, "unsupported")))
            await writer.drain()
    except (asyncio.IncompleteReadError, ConnectionError): pass
    except Exception as e: log(svc="ldap", ev="error", err=repr(e))
    writer.close()

# ---------------- MSSQL (TDS 7.x) ----------------
def tds(ptype, payload, status=1): return struct.pack(">BBHHBB", ptype, status, len(payload) + 8, 0, 1, 0) + payload
def prelogin_response(version=(15, 0, 2000, 5)):
    opts = [(0, struct.pack(">BBHH", version[0], version[1], version[2], version[3])), (1, b"\x02"), (2, b"\x00"), (4, b"\x00")]
    head, data, off = b"", b"", 5 * len(opts) + 1
    for tok, val in opts: head += struct.pack(">BHH", tok, off + len(data), len(val)); data += val
    return tds(4, head + b"\xff" + data)
def us_varchar(s): return struct.pack("<B", len(s)) + s.encode("utf-16le")
def login_ack_stream(server="FS01", legacy=False):
    ver = b"Microsoft SQL Server"; ack = b"\x01" + struct.pack(">I", 0x74000004) + us_varchar("Microsoft SQL Server") + struct.pack(">BBBB", 15, 0, 0x10, 0xA5)
    out = b"\xad" + struct.pack("<H", len(ack)) + ack
    env = lambda t, a, b: b"\xe3" + struct.pack("<H", 1 + len(a) + len(b) + 2) + bytes([t]) + bytes([len(a) // 2]) + a + bytes([len(b) // 2]) + b
    out += env(1, "master".encode("utf-16le"), "master".encode("utf-16le"))
    out += env(4, "4096".encode("utf-16le"), "4096".encode("utf-16le"))
    msg = "Changed database context to 'master'."
    info = struct.pack("<IBB", 5701, 1, 10) + struct.pack("<H", len(msg)) + msg.encode("utf-16le") + us_varchar(server) + us_varchar("") + struct.pack("<I", 1)
    out += b"\xab" + struct.pack("<H", len(info)) + info
    return out + done(legacy=legacy)
def done(count=0, status=0, legacy=False):
    return b"\xfd" + struct.pack("<HH", status | (0x10 if count else 0), 0x00c1 if count else 0x00fd) + (struct.pack("<I", count) if legacy else struct.pack("<Q", count))
def one_row(colname, value, legacy=False):
    col = b"\x81" + struct.pack("<H", 1) + (struct.pack("<HH", 0, 0x21) if legacy else struct.pack("<IH", 0, 0x21)) + b"\xe7" + struct.pack("<H", 8000) + b"\x09\x04\xd0\x00\x34" + us_varchar(colname)
    row = b"\xd1" + struct.pack("<H", len(value) * 2) + value.encode("utf-16le")
    return col + row + done(1, legacy=legacy)
def deobf_pw(b): return bytes(((x ^ 0xA5) >> 4 | ((x ^ 0xA5) & 0x0F) << 4) & 0xFF for x in b).decode("utf-16le")
SQL_VERSION = "Microsoft SQL Server 2019 (RTM-CU18) (KB5017593) - 15.0.4261.1 (X64) \n\tSep 12 2022 15:07:06 \n\tCopyright (C) 2019 Microsoft Corporation\n\tStandard Edition (64-bit) on Windows Server 2019 Standard 10.0 <X64> (Build 17763: ) (Hypervisor)\n"
async def read_tds(reader):
    h = await reader.readexactly(8); n = struct.unpack(">H", h[2:4])[0]
    return h[0], await reader.readexactly(n - 8)
async def mssql_conn(reader, writer):
    peer = writer.get_extra_info("peername")[0]; log(svc="mssql", ev="connect", src=peer); chal = os.urandom(8); conn_state = {}
    try:
        while True:
            t, p = await read_tds(reader)
            if t == 0x12: writer.write(prelogin_response())
            elif t == 0x10:
                fields = struct.unpack("<IIIIIIBBBBiI", p[:36]); off = lambda i: struct.unpack("<HH", p[36 + 4 * i: 40 + 4 * i])
                hn, un, pw, app = (off(i) for i in range(4)); (ssp_off, ssp_len) = struct.unpack("<HH", p[78:82]) if len(p) >= 82 else (0, 0)
                user = p[un[0]: un[0] + un[1] * 2].decode("utf-16le"); pwd = deobf_pw(p[pw[0]: pw[0] + pw[1] * 2])
                host = p[hn[0]: hn[0] + hn[1] * 2].decode("utf-16le"); appn = p[app[0]: app[0] + app[1] * 2].decode("utf-16le")
                sspi = fields[6] & 0x80  # optFlags2 fSSPI? (bit 7 of OptionFlags2 in the 7th byte)
                conn_state["legacy"] = struct.unpack("<I", p[4:8])[0] < 0x72090002
                log(svc="mssql", ev="login7", src=peer, tds=hex(struct.unpack("<I", p[4:8])[0]), user=user, password=pwd, client_host=host, app=appn, sspi_len=ssp_len)
                if ssp_len:
                    sspi_tok = p[ssp_off: ssp_off + ssp_len]; blob = find_ntlmssp(sspi_tok); conn_state["sspi"] = True
                    ch = challenge_message(HOST_NAME, DOMAIN, chal)
                    writer.write(tds(4, b"\xed" + struct.pack("<H", len(ch)) + ch))
                else:
                    writer.write(tds(4, login_ack_stream(legacy=conn_state["legacy"])))
            elif t == 0x11:
                blob = find_ntlmssp(p)
                if blob and ntlm_type(blob) == 3: log(svc="mssql", ev="ntlm", src=peer, **parse_authenticate(blob, chal))
                msg = "Login failed for user ''."; err = struct.pack("<IBB", 18456, 1, 14) + struct.pack("<H", len(msg)) + msg.encode("utf-16le") + us_varchar(HOST_NAME) + us_varchar("") + struct.pack("<I", 1)
                writer.write(tds(4, b"\xaa" + struct.pack("<H", len(err)) + err + done(0, 0x02)))
            elif t == 0x01:
                text = p[22:].decode("utf-16le", "replace") if p[:4] == b"\x16\x00\x00\x00" else p.decode("utf-16le", "replace")
                log(svc="mssql", ev="batch", src=peer, sql=text[:300])
                low = text.lower()
                if "@@version" in low: writer.write(tds(4, one_row("", SQL_VERSION, conn_state.get("legacy", False))))
                else: writer.write(tds(4, done(legacy=conn_state.get("legacy", False))))
            else: break
            await writer.drain()
    except (asyncio.IncompleteReadError, ConnectionError): pass
    except Exception as e: log(svc="mssql", ev="error", err=repr(e))
    writer.close()

# ---------------- WinRM (HTTP 5985) ----------------
IDENTIFY = ('<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" xmlns:wsmid="http://schemas.dmtf.org/wbem/wsman/identity/1/wsmanidentity.xsd">'
            '<s:Header/><s:Body><wsmid:IdentifyResponse><wsmid:ProtocolVersion>http://schemas.dmtf.org/wbem/wsman/1/wsman.xsd</wsmid:ProtocolVersion>'
            '<wsmid:ProductVendor>Microsoft Corporation</wsmid:ProductVendor><wsmid:ProductVersion>OS: 0.0.0 SP: 0.0 Stack: 3.0</wsmid:ProductVersion>'
            '</wsmid:IdentifyResponse></s:Body></s:Envelope>')
def http(status, headers, body=b""):
    reason = {200: "OK", 401: "Unauthorized"}[status]
    h = "".join(f"{k}: {v}\r\n" for k, v in headers)
    return f"HTTP/1.1 {status} {reason}\r\n{h}Content-Length: {len(body)}\r\nServer: Microsoft-HTTPAPI/2.0\r\n\r\n".encode() + body
async def winrm_conn(reader, writer):
    peer = writer.get_extra_info("peername")[0]; log(svc="winrm", ev="connect", src=peer); chal = os.urandom(8)
    try:
        while True:
            head = await reader.readuntil(b"\r\n\r\n"); lines = head.decode("latin1").split("\r\n"); req = lines[0]
            hdrs = {l.split(":", 1)[0].lower(): l.split(":", 1)[1].strip() for l in lines[1:] if ":" in l}
            body = await reader.readexactly(int(hdrs.get("content-length", 0))) if int(hdrs.get("content-length", 0)) else b""
            auth = hdrs.get("authorization", "")
            if b"Identify" in body and not auth:
                log(svc="winrm", ev="identify", src=peer, request=req)
                writer.write(http(200, [("Content-Type", "application/soap+xml;charset=UTF-8")], IDENTIFY.encode()))
            elif auth.lower().startswith(("negotiate ", "ntlm ")):
                tok = base64.b64decode(auth.split(" ", 1)[1]); blob = find_ntlmssp(tok)
                if blob and ntlm_type(blob) == 1:
                    writer.write(http(401, [("WWW-Authenticate", "Negotiate " + base64.b64encode(challenge_message(HOST_NAME, DOMAIN, chal)).decode()), ("Connection", "Keep-Alive")]))
                elif blob and ntlm_type(blob) == 3:
                    log(svc="winrm", ev="ntlm", src=peer, request=req, **parse_authenticate(blob, chal))
                    writer.write(http(401, [("WWW-Authenticate", "Negotiate"), ("WWW-Authenticate", 'Basic realm="WSMAN"')]))
                else: writer.write(http(401, [("WWW-Authenticate", "Negotiate")]))
            elif auth.lower().startswith("basic "):
                log(svc="winrm", ev="basic", src=peer, creds=base64.b64decode(auth.split()[1]).decode("latin1"))
                writer.write(http(401, [("WWW-Authenticate", "Negotiate"), ("WWW-Authenticate", 'Basic realm="WSMAN"')]))
            else:
                log(svc="winrm", ev="unauth", src=peer, request=req)
                writer.write(http(401, [("WWW-Authenticate", "Negotiate"), ("WWW-Authenticate", 'Basic realm="WSMAN"'), ("Connection", "Keep-Alive")]))
            await writer.drain()
            if req.endswith("HTTP/1.0") or hdrs.get("connection", "").lower() == "close": break
    except (asyncio.IncompleteReadError, ConnectionError, asyncio.LimitOverrunError): pass
    except Exception as e: log(svc="winrm", ev="error", err=repr(e))
    writer.close()

# ---------------- RDP (X.224 negotiation only) ----------------
def tlv(tag, content):
    n = len(content)
    ln = bytes([n]) if n < 128 else (b"\x82" + n.to_bytes(2, "big") if n < 65536 else b"\x83" + n.to_bytes(3, "big"))
    return bytes([tag]) + ln + content
def ts_request(token=None, error=None):
    body = tlv(0xA0, tlv(0x02, b"\x06"))
    if token is not None: body += tlv(0xA1, tlv(0x30, tlv(0x30, tlv(0xA0, tlv(0x04, token)))))
    if error is not None: body += tlv(0xA4, tlv(0x02, struct.pack(">i", error)))
    return tlv(0x30, body)
_ctx = []
def tls_context():
    if _ctx: return _ctx[0]
    import datetime, ssl, tempfile
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "FS01.corp.local")])
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(datetime.datetime(2026, 1, 1)).not_valid_after(datetime.datetime(2036, 1, 1)).sign(key, hashes.SHA256()))
    d = tempfile.mkdtemp(); open(d + "/c.pem", "wb").write(cert.public_bytes(serialization.Encoding.PEM))
    open(d + "/k.pem", "wb").write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); ctx.load_cert_chain(d + "/c.pem", d + "/k.pem"); _ctx.append(ctx); return ctx
async def credssp(reader, writer, peer):
    chal = os.urandom(8)
    while True:
        data = await asyncio.wait_for(reader.read(65536), 10)
        if not data: return
        blob = find_ntlmssp(data)
        if blob and ntlm_type(blob) == 1:
            writer.write(ts_request(token=spnego_challenge(challenge_message(HOST_NAME, DOMAIN, chal)))); await writer.drain()
        elif blob and ntlm_type(blob) == 3:
            log(svc="rdp", ev="ntlm", src=peer, **parse_authenticate(blob, chal))
            writer.write(ts_request(error=-1073741715)); await writer.drain(); return   # 0xC000006D STATUS_LOGON_FAILURE
        else:
            log(svc="rdp", ev="credssp_other", src=peer, head=data[:16].hex()); return
RDP_SELECT = int(os.environ.get("RDP_SELECT", "1"))   # 0 RDP, 1 SSL, 2 HYBRID
async def rdp_conn(reader, writer):
    peer = writer.get_extra_info("peername")[0]
    try:
        hdr = await reader.readexactly(4); n = struct.unpack(">H", hdr[2:4])[0]; body = await reader.readexactly(n - 4)
        cookie = body[7:].split(b"\r\n")[0][:80] if b"Cookie" in body else b""
        req = body[-8:] if len(body) >= 15 and body[-8] == 1 else b""
        log(svc="rdp", ev="x224_request", src=peer, cookie=cookie.decode("latin1"), requested=struct.unpack("<I", req[4:8])[0] if req else None)
        neg = struct.pack("<BBHI", 2, 0, 8, RDP_SELECT)
        x224 = b"\xd0\x00\x00\x12\x34\x00" + neg
        writer.write(b"\x03\x00" + struct.pack(">H", 4 + 1 + len(x224)) + bytes([len(x224)]) + x224); await writer.drain()
        if RDP_SELECT == 0:
            extra = await asyncio.wait_for(reader.read(4096), 5); log(svc="rdp", ev="after_cc", src=peer, bytes=len(extra), head=extra[:8].hex())
        else:
            await writer.start_tls(tls_context())
            if RDP_SELECT == 2: await credssp(reader, writer, peer)
    except Exception as e: log(svc="rdp", ev="error", err=repr(e))
    writer.close()

async def main():
    addr = sys.argv[1]; ports = dict(a.split("=") for a in sys.argv[2:]); servers = []
    if "ssh" in ports: await start_ssh(addr, int(ports["ssh"]))
    for name, handler in (("ldap", ldap_conn), ("mssql", mssql_conn), ("winrm", winrm_conn), ("rdp", rdp_conn)):
        if name in ports: servers.append(await asyncio.start_server(handler, addr, int(ports[name])))
    log(svc="standin", ev="up", ports=ports)
    await asyncio.Event().wait()
asyncio.run(main())
