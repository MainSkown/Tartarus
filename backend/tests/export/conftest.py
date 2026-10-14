from datetime import UTC, datetime

import pytest

from app.export.inputs import (
    ExportAnnotations,
    ExportNote,
    ExportSample,
    ExportTechnique,
    IocExportInput,
    TargetType,
)
from app.schemas.views_events import ProcessRef
from app.schemas.views_findings import Ioc, IocType

SAMPLE_SHA256 = "a" * 64
SAMPLE_MD5 = "b" * 32
SAMPLE_SHA1 = "c" * 40
DROPPED_SHA256 = "d" * 64
OBSERVED_AT = datetime(2026, 10, 13, 12, 30, 15, 250000, tzinfo=UTC)
DROPPER = ProcessRef(pid=4242, name="invoice.exe")


def make_ioc(
    type_: IocType,
    value: str,
    context: str = "",
    process: ProcessRef | None = None,
    event_ids: list[str] | None = None,
) -> Ioc:
    return Ioc(
        type=type_,
        value=value,
        count=1,
        context=context,
        source_event_ids=event_ids or [],
        process=process,
    )


EVERY_TYPE = (
    make_ioc(IocType.HASH, SAMPLE_SHA256, "Submitted sample invoice.exe"),
    make_ioc(IocType.HASH, DROPPED_SHA256, "Dropped file stage2.dll", DROPPER),
    make_ioc(IocType.DOMAIN, "evil.example", "DNS query evil.example", DROPPER, ["ev-dns"]),
    make_ioc(IocType.IP, "203.0.113.7", "Connection to 203.0.113.7:443", DROPPER),
    make_ioc(IocType.IP, "2001:db8::1", "Connection to [2001:db8::1]:443", DROPPER),
    make_ioc(IocType.URL, "http://evil.example/a.php?x=1&y='2'", "GET /a.php", DROPPER),
    make_ioc(IocType.MUTEX, "Global\\Tartarus-Mutex", "Mutex named in the behavior summary"),
    make_ioc(
        IocType.REGISTRY,
        "HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\Run\\evil",
        "Set value Run\\evil",
        DROPPER,
    ),
    make_ioc(IocType.FILE, "C:\\Users\\victim\\AppData\\Roaming\\stage2.dll", "Create file"),
)

SAMPLE = ExportSample(
    filename="invoice.exe", sha256=SAMPLE_SHA256, md5=SAMPLE_MD5, sha1=SAMPLE_SHA1
)
TECHNIQUES = (
    ExportTechnique("T1059", "Command and Scripting Interpreter"),
    ExportTechnique("T1547.001", "Registry Run Keys / Startup Folder"),
    ExportTechnique("T9999", None),
)
NOTES = (
    ExportNote("Looks like an Emotet dropper.", TargetType.ANALYSIS, None),
    ExportNote("Spawns the DNS lookups.", TargetType.PROCESS, "4242"),
    ExportNote("The beacon, check the URI.", TargetType.EVENT, "ev-dns"),
)


@pytest.fixture
def make_input():
    def build(**changes: object) -> IocExportInput:
        fields: dict[str, object] = {
            "analysis_id": 7,
            "sample": SAMPLE,
            "observed_at": OBSERVED_AT,
            "iocs": EVERY_TYPE,
            "families": ("emotet",),
            "techniques": TECHNIQUES,
            "annotations": ExportAnnotations(tags=("phishing", "needs-review"), notes=NOTES),
        }
        return IocExportInput(**{**fields, **changes})  # type: ignore[arg-type]

    return build
