"""The fake host's service table: what svcctl clients create, kept in memory and never started."""

from dataclasses import dataclass, field

MAX_SERVICES = 256
MAX_NAME_CHARS = 256
MAX_BINARY_PATH_CHARS = 4096
SERVICE_STOPPED, SERVICE_RUNNING = 1, 4
SERVICE_WIN32_OWN_PROCESS = 0x10
ERROR_SERVICE_EXISTS = 1073
ERROR_SERVICE_DOES_NOT_EXIST = 1060
ERROR_INVALID_NAME = 123
ERROR_NOT_ENOUGH_MEMORY = 8
ERROR_SERVICE_ALREADY_RUNNING = 1056

_CANNED = (
    (
        "EventLog",
        "Windows Event Log",
        r"C:\Windows\System32\svchost.exe -k LocalServiceNetworkRestricted",
    ),
    ("LanmanServer", "Server", r"C:\Windows\System32\svchost.exe -k netsvcs"),
    ("Spooler", "Print Spooler", r"C:\Windows\System32\spoolsv.exe"),
    ("W32Time", "Windows Time", r"C:\Windows\System32\svchost.exe -k LocalService"),
)


class ServiceError(Exception):
    """A Win32 error code the service control manager answers with."""

    def __init__(self, code: int) -> None:
        super().__init__(str(code))
        self.code = code


@dataclass
class ServiceRecord:
    name: str
    display_name: str
    binary_path: str
    service_type: int = SERVICE_WIN32_OWN_PROCESS
    start_type: int = 3
    state: int = SERVICE_STOPPED


@dataclass
class ServiceTable:
    records: dict[str, ServiceRecord] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name, display, path in _CANNED:
            self.records[name.casefold()] = ServiceRecord(
                name, display, path, state=SERVICE_RUNNING
            )

    def create(
        self, name: str, display_name: str, binary_path: str, **fields: int
    ) -> ServiceRecord:
        if not name or len(name) > MAX_NAME_CHARS or "\\" in name or "/" in name:
            raise ServiceError(ERROR_INVALID_NAME)
        if name.casefold() in self.records:
            raise ServiceError(ERROR_SERVICE_EXISTS)
        if len(self.records) >= MAX_SERVICES:
            raise ServiceError(ERROR_NOT_ENOUGH_MEMORY)
        record = ServiceRecord(
            name,
            display_name[:MAX_NAME_CHARS] or name,
            binary_path[:MAX_BINARY_PATH_CHARS],
            **fields,
        )
        self.records[name.casefold()] = record
        return record

    def get(self, name: str) -> ServiceRecord:
        try:
            return self.records[name.casefold()]
        except KeyError:
            raise ServiceError(ERROR_SERVICE_DOES_NOT_EXIST) from None

    def delete(self, name: str) -> None:
        self.get(name)
        del self.records[name.casefold()]

    def listing(self) -> list[ServiceRecord]:
        return sorted(self.records.values(), key=lambda record: record.name.casefold())
