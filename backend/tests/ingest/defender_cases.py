import shutil
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from app.ingest.protocol import IngestContext

FIXTURES = Path(__file__).parent.parent / "fixtures" / "windows_events"
NS = "http://schemas.microsoft.com/win/2004/08/events/event"
ANALYSIS_ID = 41
GUEST_LAG = timedelta(hours=2)

EICAR_STARTED = datetime(2026, 10, 18, 23, 33, 45, tzinfo=UTC)
EICAR_TASK = 321
DROPPED_STARTED = datetime(2026, 10, 18, 23, 20, 0, tzinfo=UTC)
DROPPED_TASK = 315
DEFAULT_IMAGE = r"C:\Users\Alice\AppData\Local\Temp\sample.exe"
DROPPER_IMAGE = r"C:\Users\Alice\AppData\Local\Temp\dropper.exe"
EICAR_SAMPLE_PATH = r"C:\Users\Alice\AppData\Local\Temp\321\eicar.com"
EICAR_DETECTION = "{2F76116E-F537-4C6D-9327-BE2C781A26F9}"


def report_of(
    task_id: int, started: datetime, images: tuple[str, ...] = (DEFAULT_IMAGE,)
) -> dict[str, Any]:
    """A CAPE report whose one monitored process starts exactly GUEST_LAG behind the host clock."""
    guest_first_seen = (started - GUEST_LAG).strftime("%Y-%m-%d %H:%M:%S")
    return {
        "info": {"id": task_id, "started": started.strftime("%Y-%m-%d %H:%M:%S")},
        "target": {"file": {"name": "eicar.com"}},
        "behavior": {
            "processes": [
                {"process_id": 1000 + index, "module_path": image, "first_seen": guest_first_seen}
                for index, image in enumerate(images)
            ]
        },
    }


def context_of(analysis_dir: Path | None, started: datetime = EICAR_STARTED) -> IngestContext:
    return IngestContext(analysis_id=ANALYSIS_ID, started_at=started, analysis_dir=analysis_dir)


def copy_export(root: Path, fixture: str) -> Path:
    (root / "aux").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(FIXTURES / fixture, root / "aux" / "defender.xml")
    return root


def write_export(root: Path, text: str) -> Path:
    (root / "aux").mkdir(parents=True, exist_ok=True)
    (root / "aux" / "defender.xml").write_text(text, encoding="utf-8")
    return root


def export_xml(*events: str) -> str:
    return "<Events>\n" + "\n".join(events) + "\n</Events>\n"


def event_xml(event_id: int, record_id: int, system_time: str, data: Mapping[str, str]) -> str:
    fields = "".join(f"<Data Name='{name}'>{escape(value)}</Data>" for name, value in data.items())
    return (
        f"<Event xmlns='{NS}'><System><EventID>{event_id}</EventID>"
        f"<TimeCreated SystemTime='{system_time}'/><EventRecordID>{record_id}</EventRecordID>"
        f"</System><EventData>{fields}</EventData></Event>"
    )


DATA_NAMES = {
    "detection_id": "Detection ID",
    "threat_id": "Threat ID",
    "threat_name": "Threat Name",
    "severity_id": "Severity ID",
    "action_id": "Action ID",
}


def detection_data(
    path: str = EICAR_SAMPLE_PATH, process: str = r"C:\Python311\pythonw.exe", **fields: str
) -> dict[str, str]:
    """A 1116 record's Data; `fields` override by snake_case name (see DATA_NAMES)."""
    overrides = {DATA_NAMES[name]: value for name, value in fields.items()}
    threat_name = overrides.get("Threat Name", "Virus:DOS/EICAR_Test_File")
    data = {
        "Detection ID": EICAR_DETECTION,
        "Threat ID": "2147519003",
        "Threat Name": threat_name,
        "Severity ID": "5",
        "Category ID": "42",
        "Category Name": "Wirus",
        "FWLink": f"https://go.microsoft.com/fwlink/?linkid=37020&name={threat_name}",
        "Status Code": "1",
        "State": "1",
        "Source ID": "3",
        "Process Name": process,
        "Detection User": "DESKTOP-2YK5XLK\\Alice",
        "Remediation User": "",
        "Path": f"file:_{path}",
        "Action ID": "9",
        "Error Code": "0x00000000",
        "Error Description": "Operacja ukończona pomyślnie.",
    }
    return data | overrides


def closing_data(
    detection_id: str = EICAR_DETECTION, action_id: str = "2", **extra: str
) -> dict[str, str]:
    data = detection_data(detection_id=detection_id, action_id=action_id, **extra)
    data["Remediation User"] = "ZARZĄDZANIE NT\\SYSTEM"
    data["Status Code"] = "3"
    return data
