"""SMB stand-in: impacket SimpleSMBServer + a fake svcctl pipe (logs, never executes) on a DCERPCServer."""
import sys, os, logging, threading
from impacket import smbserver
from impacket.dcerpc.v5.rpcrt import DCERPCServer
from impacket.dcerpc.v5 import scmr
from impacket.dcerpc.v5.dtypes import NULL

LOG = logging.getLogger("lan")

class SvcctlServer(DCERPCServer):
    def __init__(self, client_socket=None):
        DCERPCServer.__init__(self, client_socket)
        self.addCallbacks(("367ABB81-9844-35F1-AD32-98F038001003", "2.0"), "\\PIPE\\svcctl", {
            0: self.close, 2: self.delete, 6: self.query_status, 12: self.create, 15: self.open_scm,
            16: self.open_service, 14: self.enum_services, 19: self.start_service})
    def serve(self):
        try:
            while (data := self.recv()) is not None:
                answer = self.processRequest(data)
                if answer is not None: self.send(answer)
        except Exception: pass
        self._clientSock.close()
    def run(self):
        # impacket serves one connection at a time; a client that holds a pipe would block all others
        self._sock.listen(50)
        while True:
            sock, _ = self._sock.accept()
            threading.Thread(target=SvcctlServer(sock).serve, daemon=True).start()
    def _handle(self): return b"\x00" * 4 + os.urandom(16)
    def open_scm(self, data):
        r = scmr.ROpenSCManagerW(data); LOG.info("svcctl OpenSCManagerW machine=%s", r["lpMachineName"])
        a = scmr.ROpenSCManagerWResponse(); a["lpScHandle"] = self._handle(); a["ErrorCode"] = 0; return a
    def create(self, data):
        r = scmr.RCreateServiceW(data)
        LOG.info("svcctl CreateServiceW name=%s display=%s binary=%s start=%s", r["lpServiceName"], r["lpDisplayName"], r["lpBinaryPathName"], r["dwStartType"])
        a = scmr.RCreateServiceWResponse(); a["lpdwTagId"] = NULL; a["lpServiceHandle"] = self._handle(); a["ErrorCode"] = 0; return a
    def open_service(self, data):
        r = scmr.ROpenServiceW(data); LOG.info("svcctl OpenServiceW name=%s", r["lpServiceName"])
        a = scmr.ROpenServiceWResponse(); a["lpServiceHandle"] = self._handle(); a["ErrorCode"] = 0; return a
    def start_service(self, data):
        LOG.info("svcctl StartServiceW"); a = scmr.RStartServiceWResponse(); a["ErrorCode"] = 0; return a
    def enum_services(self, data):
        a = scmr.REnumServicesStatusWResponse(); a["lpBuffer"] = b""; a["pcbBytesNeeded"] = 0
        a["lpServicesReturned"] = 0; a["lpResumeIndex"] = NULL; a["ErrorCode"] = 0; return a
    def delete(self, data):
        LOG.info("svcctl DeleteService"); a = scmr.RDeleteServiceResponse(); a["ErrorCode"] = 0; return a
    def query_status(self, data):
        a = scmr.RQueryServiceStatusResponse()
        for k, v in (("dwServiceType", 0x10), ("dwCurrentState", 4), ("dwControlsAccepted", 1)): a["lpServiceStatus"][k] = v
        a["ErrorCode"] = 0; return a
    def close(self, data):
        a = scmr.RCloseServiceHandleResponse(); a["hSCObject"] = b"\x00" * 20; a["ErrorCode"] = 0; return a

addr, port = sys.argv[1], int(sys.argv[2])
for d in ("/srv/c/Windows", "/srv/admin", "/srv/data"): os.makedirs(d, exist_ok=True)
server = smbserver.SimpleSMBServer(listenAddress=addr, listenPort=port)
server.addShare("ADMIN$", "/srv/admin", "Remote Admin"); server.addShare("C$", "/srv/c", "Default share"); server.addShare("DATA", "/srv/data", "data")
server.setSMB2Support(True); server.setSMBChallenge(""); server.setLogFile("/tmp/smb-ntlm.log")
if os.environ.get("SMB_CRED"):
    from impacket import ntlm
    u, pw = os.environ["SMB_CRED"].split(":", 1)
    server.addCredential(u, 1000, "", ntlm.compute_nthash(pw).hex())
svc = SvcctlServer(); svc.daemon = True; svc.start()
from impacket import smb3structs as smb2
_orig = []
def _non_guest(connId, smbServer, recvPacket):
    cmds, pkts, err = _orig[0](connId, smbServer, recvPacket)
    if err == 0 and hasattr(cmds[0], "fields") and "SessionFlags" in cmds[0].fields: cmds[0]["SessionFlags"] = 0
    return cmds, pkts, err
_orig.append(server.getServer().hookSmb2Command(smb2.SMB2_SESSION_SETUP, _non_guest))
_orig_neg = []
def _no_signing(connId, smbServer, recvPacket, *rest):
    cmds, pkts, err = _orig_neg[0](connId, smbServer, recvPacket, *rest)
    if os.environ.get("SMB_SIGNING", "1") == "0" and cmds and "SecurityMode" in cmds[0].fields: cmds[0]["SecurityMode"] = 0
    return cmds, pkts, err
_orig_neg.append(server.getServer().hookSmb2Command(smb2.SMB2_NEGOTIATE, _no_signing))
PIPES = {"svcctl", "srvsvc", "wkssvc"}
_orig_create = []
def _ipc_is_read_only(connId, smbServer, recvPacket):
    from impacket.smbserver import STATUS_ACCESS_DENIED
    connData = smbServer.getConnectionData(connId)
    share = connData["ConnectedShares"].get(recvPacket["TreeID"], {}).get("shareName", "")
    name = smb2.SMB2Create(recvPacket["Data"])["Buffer"].decode("utf-16le").lower().strip("\\")
    if share == "IPC$" and name not in PIPES:
        return [smb2.SMB2Error()], None, STATUS_ACCESS_DENIED
    request = smb2.SMB2Create(recvPacket["Data"])
    if request["CreateOptions"] & 0x1:      # FILE_DIRECTORY_FILE: opening a directory for write is allowed on Windows
        request["DesiredAccess"] = 0x80      # FILE_READ_ATTRIBUTES
        recvPacket["Data"] = request.getData()
    return _orig_create[0](connId, smbServer, recvPacket)
_orig_create.append(server.getServer().hookSmb2Command(smb2.SMB2_CREATE, _ipc_is_read_only))
server.registerNamedPipe("svcctl", ("127.0.0.1", svc.getListenPort()))
server.start()
