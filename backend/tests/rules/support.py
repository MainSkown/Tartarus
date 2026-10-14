import textwrap
from pathlib import Path

DEFAULT_RULESET = Path(__file__).resolve().parents[3] / "rules" / "sigma" / "default"

DEFAULT_ID = "5a9a1d6e-0b6b-4a3c-8d3e-1c2f3a4b5c6d"


def rule_yaml(  # noqa: PLR0913 - one keyword per field a test may vary
    detection: str,
    *,
    category: str | None = "process_creation",
    product: str | None = "windows",
    rule_id: str | None = DEFAULT_ID,
    title: str = "Test rule",
    level: str | None = "high",
    tags: tuple[str, ...] = (),
    extra: str = "",
) -> str:
    """A rule document; `detection` is the body under `detection:` (indented here)."""
    logsource = {"category": category, "product": product}
    lines = ["title: " + title]
    if rule_id is not None:
        lines.append(f"id: {rule_id}")
    lines += ["status: test", "description: A rule for the tests"]
    if level is not None:
        lines.append(f"level: {level}")
    if tags:
        lines += ["tags:", *(f"    - {tag}" for tag in tags)]
    lines.append("logsource:")
    lines += [f"    {key}: {value}" for key, value in logsource.items() if value is not None]
    lines.append("detection:")
    lines.append(textwrap.indent(textwrap.dedent(detection).strip("\n"), "    "))
    if extra:
        lines.append(extra)
    return "\n".join(lines) + "\n"


def simple_detection(selection: str, condition: str = "selection") -> str:
    body = textwrap.indent(textwrap.dedent(selection).strip("\n"), "  ")
    return f"selection:\n{body}\ncondition: {condition}"


def process_event(  # noqa: PLR0913 - one keyword per field a test may vary
    event_id: str = "evt-1",
    time: str = "2026-10-13T10:00:00.000Z",
    *,
    entity_id: str | None = "7:100@2026-10-13T09:59:00.000Z",
    command_line: str = "cmd.exe /c whoami",
    action: str = "process-created",
    lane: str = "process",
) -> dict[str, object]:
    """A document shaped like the normalisers' output, with the fields rules read."""
    process: dict[str, object] = {
        "pid": 100,
        "name": "cmd.exe",
        "executable": "C:\\Windows\\System32\\cmd.exe",
        "command_line": command_line,
    }
    if entity_id is not None:
        process["entity_id"] = entity_id
    return {
        "@timestamp": time,
        "event": {"id": event_id, "kind": "event", "action": action, "sequence": 0},
        "tartarus": {"analysis_id": 7, "lane": lane, "summary": "x"},
        "process": process,
    }
