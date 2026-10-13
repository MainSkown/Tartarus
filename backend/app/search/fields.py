from dataclasses import dataclass
from enum import StrEnum


class FieldType(StrEnum):
    KEYWORD = "keyword"
    TEXT = "text"
    KEYWORD_WITH_TEXT = "keyword_with_text"
    LONG = "long"
    INTEGER = "integer"
    DATE = "date"
    IP = "ip"
    BOOLEAN = "boolean"
    FLAT_OBJECT = "flat_object"
    OBJECT_DISABLED = "object_disabled"


class Lane(StrEnum):
    PROCESS = "process"
    FILE = "file"
    REGISTRY = "registry"
    NETWORK = "network"
    MEMORY = "memory"
    API = "api"


@dataclass(frozen=True, slots=True)
class FieldDefinition:
    """One event field. `lane` is set only on fields that belong to a single lane's category."""

    name: str
    type: FieldType
    description: str
    example: str
    lane: Lane | None = None
    aliases: tuple[str, ...] = ()


_K = FieldType.KEYWORD
_KT = FieldType.KEYWORD_WITH_TEXT
_LONG = FieldType.LONG

_COMMON = (
    FieldDefinition(
        "@timestamp", FieldType.DATE, "Guest event time in UTC", "2026-10-13T10:12:41.123Z"
    ),
    FieldDefinition("event.id", _K, "Deterministic id of the event", "3f786850e387550fdab836ed"),
    FieldDefinition("event.sequence", _LONG, "Order of the event within the analysis", "1042"),
    FieldDefinition(
        "event.kind", _K, "`event`, or `alert` for detections", "alert", aliases=("kind",)
    ),
    FieldDefinition(
        "event.category", _K, "ECS categories of the event", "process", aliases=("category",)
    ),
    FieldDefinition("event.type", _K, "ECS types of the event", "start"),
    FieldDefinition(
        "event.action", _K, "Specific action performed", "process-created", aliases=("action",)
    ),
    FieldDefinition("event.module", _K, "Source that produced the event", "capemon"),
    FieldDefinition("event.dataset", _K, "Dataset within the source", "capemon.api"),
    FieldDefinition(
        "event.severity",
        FieldType.INTEGER,
        "0 info, 1 low, 2 medium, 3 high, 4 critical (alerts only)",
        "3",
        aliases=("severity",),
    ),
    FieldDefinition("tartarus.analysis_id", _LONG, "Id of the analysis the event belongs to", "6"),
    FieldDefinition(
        "tartarus.lane",
        _K,
        "Timeline lane: process, file, registry, network, memory or api",
        "file",
        aliases=("lane",),
    ),
    FieldDefinition("tartarus.phase", _K, "Phase that produced the event: live or final", "final"),
    FieldDefinition(
        "tartarus.summary",
        _KT,
        "One-line human summary of the event",
        r"cmd.exe wrote C:\Users\victim\a.ps1",
        aliases=("summary",),
    ),
    FieldDefinition(
        "tartarus.raw", FieldType.OBJECT_DISABLED, "Original record, kept unindexed", "{...}"
    ),
)

_PROCESS = (
    FieldDefinition("process.pid", _LONG, "Process id", "2184", aliases=("pid",)),
    FieldDefinition("process.parent.pid", _LONG, "Parent process id", "1020", aliases=("ppid",)),
    FieldDefinition("process.thread.id", _LONG, "Thread id", "3312", aliases=("tid",)),
    FieldDefinition(
        "process.name", _K, "Process image file name", "cmd.exe", aliases=("process", "proc")
    ),
    FieldDefinition("process.parent.name", _K, "Parent process image file name", "explorer.exe"),
    FieldDefinition(
        "process.executable",
        _KT,
        "Full path of the process image",
        r"C:\Windows\System32\cmd.exe",
        aliases=("image",),
    ),
    FieldDefinition(
        "process.command_line",
        _KT,
        "Command line the process was started with",
        "cmd.exe /c whoami",
        aliases=("cmdline",),
    ),
    FieldDefinition(
        "process.entity_id",
        _K,
        "Unique process instance: <analysis>:<pid>@<start_ts>",
        "6:2184@1760350361",
    ),
    FieldDefinition("process.start", FieldType.DATE, "Process start time", "2026-10-13T10:12:41Z"),
    FieldDefinition("process.integrity_level", _K, "Windows integrity level", "High"),
    FieldDefinition(
        "tartarus.inject.target_pid",
        _LONG,
        "Pid of the process an injection call acts on",
        "4412",
        Lane.PROCESS,
    ),
)

_FILE = (
    FieldDefinition(
        "file.path",
        _KT,
        "Full file path",
        r"C:\Users\victim\a.ps1",
        Lane.FILE,
        aliases=("path",),
    ),
    FieldDefinition("file.name", _K, "File name", "a.ps1", Lane.FILE, aliases=("filename",)),
    FieldDefinition("file.extension", _K, "File extension without the dot", "ps1", Lane.FILE),
    FieldDefinition("file.size", _LONG, "File size in bytes", "4096", Lane.FILE),
    FieldDefinition(
        "file.hash.sha256",
        _K,
        "SHA-256 of the file",
        "e3b0c44298fc1c14...",
        Lane.FILE,
        aliases=("sha256",),
    ),
    FieldDefinition(
        "file.target_path", _K, "Destination path of a rename or move", r"C:\Temp\b.ps1", Lane.FILE
    ),
)

_REGISTRY = (
    FieldDefinition(
        "registry.path",
        _K,
        "Full registry path including hive, key and value",
        r"HKLM\Software\Microsoft\Windows\CurrentVersion\Run\Updater",
        Lane.REGISTRY,
    ),
    FieldDefinition("registry.hive", _K, "Registry hive", "HKLM", Lane.REGISTRY),
    FieldDefinition(
        "registry.key",
        _K,
        "Registry key path without the hive",
        r"Software\Microsoft\Windows\CurrentVersion\Run",
        Lane.REGISTRY,
    ),
    FieldDefinition("registry.value", _K, "Registry value name", "Updater", Lane.REGISTRY),
    FieldDefinition("registry.data.type", _K, "Registry value type", "REG_SZ", Lane.REGISTRY),
    FieldDefinition(
        "registry.data.strings",
        _K,
        "Registry value data as strings",
        r"C:\Temp\a.exe",
        Lane.REGISTRY,
    ),
)

_NETWORK = (
    FieldDefinition(
        "source.ip",
        FieldType.IP,
        "Source address",
        "192.168.56.10",
        Lane.NETWORK,
        aliases=("src.ip",),
    ),
    FieldDefinition(
        "source.port", _LONG, "Source port", "49732", Lane.NETWORK, aliases=("src.port",)
    ),
    FieldDefinition(
        "destination.ip",
        FieldType.IP,
        "Destination address",
        "93.184.216.34",
        Lane.NETWORK,
        aliases=("dst.ip", "ip"),
    ),
    FieldDefinition(
        "destination.port",
        _LONG,
        "Destination port",
        "443",
        Lane.NETWORK,
        aliases=("dst.port", "port"),
    ),
    FieldDefinition(
        "destination.domain",
        _K,
        "Destination domain name",
        "example.com",
        Lane.NETWORK,
        aliases=("domain",),
    ),
    FieldDefinition("network.transport", _K, "Transport protocol", "tcp", Lane.NETWORK),
    FieldDefinition("network.protocol", _K, "Application protocol", "http", Lane.NETWORK),
    FieldDefinition(
        "dns.question.name",
        _K,
        "Name asked in a DNS query",
        "example.com",
        Lane.NETWORK,
        aliases=("dns",),
    ),
    FieldDefinition("dns.question.type", _K, "Type of a DNS query", "A", Lane.NETWORK),
    FieldDefinition(
        "dns.answers.data", _K, "Data of the DNS answers", "93.184.216.34", Lane.NETWORK
    ),
    FieldDefinition(
        "url.full", _K, "Full URL", "http://example.com/a.bin", Lane.NETWORK, aliases=("url",)
    ),
    FieldDefinition("http.request.method", _K, "HTTP request method", "GET", Lane.NETWORK),
    FieldDefinition(
        "http.response.status_code", _LONG, "HTTP response status", "200", Lane.NETWORK
    ),
    FieldDefinition(
        "user_agent.original",
        _K,
        "HTTP User-Agent header",
        "Mozilla/5.0",
        Lane.NETWORK,
        aliases=("user_agent",),
    ),
    FieldDefinition(
        "tls.server.sni", _K, "TLS server name indication", "example.com", Lane.NETWORK
    ),
    FieldDefinition(
        "tls.server.ja3s",
        _K,
        "JA3S fingerprint of the TLS server",
        "ec74a5c51106f0419184d0dd08fb05bc",
        Lane.NETWORK,
    ),
    FieldDefinition(
        "tls.client.ja3",
        _K,
        "JA3 fingerprint of the TLS client",
        "e7d705a3286e19ea42f587b344ee6865",
        Lane.NETWORK,
    ),
)

_API = (
    FieldDefinition(
        "api.name", _K, "Name of the API call", "NtWriteFile", Lane.API, aliases=("api",)
    ),
    FieldDefinition("api.category", _K, "capemon category of the call", "filesystem", Lane.API),
    FieldDefinition(
        "api.status", FieldType.BOOLEAN, "Whether the call succeeded", "true", Lane.API
    ),
    FieldDefinition("api.return_value", _K, "Return value of the call", "0", Lane.API),
    FieldDefinition(
        "api.arguments",
        FieldType.FLAT_OBJECT,
        "Arguments of the call by name",
        '{"FileName": "a.ps1"}',
        Lane.API,
    ),
    FieldDefinition(
        "api.repeated", _LONG, "Count when capemon collapsed repeated calls", "12", Lane.API
    ),
)

_MEMORY = (
    FieldDefinition(
        "tartarus.memory.plugin", _K, "Volatility plugin that found it", "malfind", Lane.MEMORY
    ),
    FieldDefinition(
        "tartarus.memory.address",
        _K,
        "Memory address of the finding",
        "0x7ff612340000",
        Lane.MEMORY,
    ),
    FieldDefinition(
        "tartarus.memory.protection",
        _K,
        "Memory protection of the region",
        "PAGE_EXECUTE_READWRITE",
        Lane.MEMORY,
    ),
    FieldDefinition(
        "tartarus.memory.dump_ref", _K, "Artifact id of the memory dump", "dump-3", Lane.MEMORY
    ),
)

_DETECTION = (
    FieldDefinition(
        "rule.id", _K, "Id of the rule that fired", "5a9a1d6e-0b6b-4a3c-8d3e-1c2f3a4b5c6d"
    ),
    FieldDefinition(
        "rule.name", _K, "Name of the rule that fired", "creates_exe_in_temp", aliases=("rule",)
    ),
    FieldDefinition(
        "rule.description",
        FieldType.TEXT,
        "What the rule detects",
        "Creates an executable in a temp directory",
    ),
    FieldDefinition(
        "rule.ruleset", _K, "sigma, cape, yara or suricata", "cape", aliases=("ruleset",)
    ),
    FieldDefinition(
        "rule.reference",
        _K,
        "Reference URLs of the rule",
        "https://attack.mitre.org/techniques/T1055/",
    ),
    FieldDefinition(
        "threat.technique.id", _K, "ATT&CK technique id", "T1055", aliases=("technique", "attack")
    ),
    FieldDefinition("threat.technique.name", _K, "ATT&CK technique name", "Process Injection"),
    FieldDefinition(
        "threat.tactic.name", _K, "ATT&CK tactic name", "Defense Evasion", aliases=("tactic",)
    ),
    FieldDefinition(
        "related.events",
        _K,
        "Ids of the events that triggered the detection",
        "3f786850e387550fdab836ed",
    ),
    FieldDefinition("related.hash", _K, "Hashes related to the detection", "e3b0c44298fc1c14..."),
    FieldDefinition(
        "related.ip", FieldType.IP, "Addresses related to the detection", "93.184.216.34"
    ),
    FieldDefinition("related.hosts", _K, "Hosts related to the detection", "example.com"),
    FieldDefinition(
        "tartarus.detection.match",
        FieldType.TEXT,
        "Text of the matched condition",
        "CommandLine contains 'powershell'",
    ),
)

FIELDS: tuple[FieldDefinition, ...] = (
    *_COMMON,
    *_PROCESS,
    *_FILE,
    *_REGISTRY,
    *_NETWORK,
    *_API,
    *_MEMORY,
    *_DETECTION,
)

_BY_NAME = {field.name: field for field in FIELDS}
_BY_NAME_OR_ALIAS = {
    **_BY_NAME,
    **{alias: field for field in FIELDS for alias in field.aliases},
}


def field_by_name(name: str) -> FieldDefinition:
    return _BY_NAME[name]


def resolve_field(name_or_alias: str) -> FieldDefinition | None:
    return _BY_NAME_OR_ALIAS.get(name_or_alias)
