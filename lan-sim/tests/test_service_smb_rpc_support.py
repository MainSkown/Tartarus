"""Stand-ins for the RPC engine tests: a log that records and a host with one account."""

from lan_session import HostSpec, ServiceSpec

HOST = HostSpec(
    "fs01.corp.local",
    "192.168.150.201",
    "Windows",
    (("Administrator", "Passw0rd!"),),
    (ServiceSpec("smb", 445),),
)


class RecordingLog:
    def __init__(self):
        self.requests = []
        self.logins = []

    def service_request(self, *, name, detail):
        self.requests.append((name, detail))
        return True

    def login_attempt(self, **fields):
        self.logins.append(fields)
        return True
