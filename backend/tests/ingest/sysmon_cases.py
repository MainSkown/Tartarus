import shutil
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from app.ingest.protocol import IngestContext
from tests.ingest.reports import call
from tests.ingest.reports import process as capemon_process
from tests.ingest.reports import report_of as capemon_report

FIXTURES = Path(__file__).parent.parent / "fixtures" / "windows_events"
BENIGN_RUN = FIXTURES / "sysmon-benign-180s.xml"
NS = "http://schemas.microsoft.com/win/2004/08/events/event"
ANALYSIS_ID = 6

# The fixture's guest clock reads two hours behind the host; the sample's `first_seen` is a few
# seconds after the guest clock's 20:43:48 (its first Sysmon event).
HOST_STARTED = datetime(2026, 10, 18, 22, 43, 30, tzinfo=UTC)
SAMPLE_FIRST_SEEN = "2026-10-18 20:43:49"

BENIGN = r"C:\Users\Megan\AppData\Local\Temp\benign.exe"
CMD = r"C:\Windows\System32\cmd.exe"
SVCHOST = r"C:\Windows\System32\svchost.exe"
AGENT = r"C:\Python311\pythonw.exe"
ANALYZER_DIR = r"C:\a349qd3t"


def guid(number: int) -> str:
    return f"{{bb84191d-0000-6ad5-{number:04x}-000000000300}}"


def monitored(
    pid: int,
    path: str,
    *,
    first_seen: str = SAMPLE_FIRST_SEEN,
    calls: list[Any] | None = None,
) -> dict[str, Any]:
    """A capemon process entry as the report lists it."""
    name = path.rsplit("\\", 1)[-1]
    entry = capemon_process(pid, calls or [], name=name)
    return {**entry, "module_path": path, "first_seen": first_seen}


def report_with(*processes: dict[str, Any]) -> dict[str, Any]:
    return {**capemon_report(*processes), "info": {"started": "2026-10-18 22:43:30"}}


def context_of(analysis_dir: Path | None) -> IngestContext:
    return IngestContext(
        analysis_id=ANALYSIS_ID, started_at=HOST_STARTED, analysis_dir=analysis_dir
    )


def analysis_with_fixture(root: Path) -> Path:
    (root / "sysmon").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(BENIGN_RUN, root / "sysmon" / "sysmon.xml")
    return root


def analysis_with(root: Path, *events: str) -> Path:
    (root / "sysmon").mkdir(parents=True, exist_ok=True)
    body = "<Events>\n" + "\n".join(events) + "\n</Events>\n"
    (root / "sysmon" / "sysmon.xml").write_text(body, encoding="utf-8")
    return root


def event_xml(event_id: int, record_id: int, utc_time: str, data: Mapping[str, str | int]) -> str:
    """A Sysmon event; `TimeCreated` trails `UtcTime` by a few hundred microseconds as it does."""
    fields = "".join(
        f"<Data Name='{name}'>{escape(str(value))}</Data>" for name, value in data.items()
    )
    system_time = utc_time.replace(" ", "T") + "4321Z"
    return (
        f"<Event xmlns='{NS}'><System><Provider Name='Microsoft-Windows-Sysmon'/>"
        f"<EventID>{event_id}</EventID><TimeCreated SystemTime='{system_time}'/>"
        f"<EventRecordID>{record_id}</EventRecordID></System><EventData>{fields}</EventData></Event>"
    )


WINDOWS = "C:\\WINDOWS\\system32\\svchost.exe"
SHELL_HOST = "C:\\Windows\\SystemApps\\ShellExperienceHost_cw5n1h2txyewy\\ShellExperienceHost.exe"
SHELL_HOST_FIRST_SEEN = "2026-10-18 20:46:38"

# The benign-run fixture is the first events per id, newest first. It holds the sample's own
# events (benign.exe, pid 8364) and plenty of Windows background; this report also lists the
# background processes whose events a test asserts on, as if they were monitored.
WIDE_REPORT = report_with(
    monitored(8364, BENIGN),
    monitored(1512, CMD),
    monitored(1604, "C:\\Windows\\System32\\svchost.exe"),
    monitored(1860, WINDOWS),
    monitored(1988, WINDOWS),
    monitored(3016, WINDOWS),
    monitored(4300, "C:\\WINDOWS\\Explorer.EXE"),
    monitored(7788, "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe"),
    monitored(
        2816,
        SHELL_HOST,
        first_seen=SHELL_HOST_FIRST_SEEN,
        calls=[
            call("NtCreateFile", {"FileName": "C:\\x"}, timestamp=SHELL_HOST_FIRST_SEEN + ",500")
        ],
    ),
)
