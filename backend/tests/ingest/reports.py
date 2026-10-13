from typing import Any

FIRST_SEEN = "2026-10-13 10:12:41,000"


def call(api: str, arguments: dict[str, str] | None = None, **fields: Any) -> dict[str, Any]:
    """A capemon call; keyword arguments override its fields (`id`, `timestamp`, `status`, ...)."""
    return {
        "timestamp": FIRST_SEEN,
        "thread_id": "100",
        "category": "misc",
        "api": api,
        "status": True,
        "return": "0x00000000",
        "arguments": [{"name": name, "value": value} for name, value in (arguments or {}).items()],
        "repeated": 0,
        "id": 0,
        **fields,
    }


def process(
    pid: int,
    calls: list[Any],
    *,
    name: str = "sample.exe",
    parent_id: int = 4,
    command_line: str = "sample.exe",
) -> dict[str, Any]:
    return {
        "process_id": pid,
        "process_name": name,
        "parent_id": parent_id,
        "module_path": f"C:\\Temp\\{name}",
        "first_seen": FIRST_SEEN,
        "calls": calls,
        "environ": {"CommandLine": command_line},
    }


def report_of(*processes: dict[str, Any]) -> dict[str, Any]:
    return {"behavior": {"processes": list(processes)}}


def report_with(*calls: dict[str, Any], pid: int = 100) -> dict[str, Any]:
    return report_of(process(pid, list(calls)))
