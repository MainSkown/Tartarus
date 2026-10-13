import json
from pathlib import Path
from typing import Any

from tests.ingest.conftest import FULL_REPORT
from tests.integration.views.conftest import ViewStack
from tests.integration.views.helpers import synthetic_event


def alert(event_id: str, name: str, severity: int, **sections: Any) -> dict[str, Any]:
    event = synthetic_event(event_id, "2026-10-13T12:13:00.000Z", "signature-matched", "process")
    event["event"] |= {"kind": "alert", "severity": severity}
    event["tartarus"] |= sections.pop("tartarus", {})
    return event | {"rule": {"name": name, **sections.pop("rule", {})}} | sections


def install_report(stack: ViewStack, report: dict[str, Any] | None = None) -> dict[str, Any]:
    document: dict[str, Any] = report or json.loads(FULL_REPORT.read_text())
    reports = stack.analysis_dir / "reports"
    reports.mkdir(exist_ok=True)
    (reports / "report.json").write_text(json.dumps(document))
    return document


def put_file(stack: ViewStack, relative: str, content: bytes) -> Path:
    path = stack.analysis_dir / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path
