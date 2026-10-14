from datetime import UTC, datetime, timedelta

from app.db.models import Analysis, Sample
from app.db.models.analysis import AnalysisStatus
from app.export.assembly import build_export_input, export_annotations
from app.export.inputs import ExportAnnotations, ExportNote, ExportTechnique, TargetType
from app.schemas.annotations import Annotations
from app.views.attack_table import AttackTable, TechniqueInfo
from tests.export.conftest import EVERY_TYPE, SAMPLE_MD5, SAMPLE_SHA1, SAMPLE_SHA256

SUBMITTED = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
TABLE = AttackTable(
    version="19.2",
    modified="2026-08-05",
    tactics=(),
    techniques={
        "T1059": TechniqueInfo("Command and Scripting Interpreter", ("execution",)),
        "T1547.001": TechniqueInfo("Registry Run Keys / Startup Folder", ("persistence",)),
    },
)


def analysis(**changes: object) -> Analysis:
    fields: dict[str, object] = {
        "id": 7,
        "sample_sha256": SAMPLE_SHA256,
        "filename": "invoice.exe",
        "status": AnalysisStatus.DONE,
        "options": {},
        "detected_families": ["emotet"],
        "submitted_at": SUBMITTED,
        "summary": {
            "techniques": [
                {"id": "T1547.001", "signatures": ["persistence_autorun"]},
                {"id": "T9999", "signatures": ["odd"]},
                {"id": "T1059", "signatures": ["a"]},
                {"id": "T1059", "signatures": ["b"]},
            ]
        },
    }
    return Analysis(**{**fields, **changes})


def sample() -> Sample:
    return Sample(sha256=SAMPLE_SHA256, md5=SAMPLE_MD5, sha1=SAMPLE_SHA1, original_name="x")


def build(**changes: object):
    arguments: dict[str, object] = {
        "analysis": analysis(),
        "sample": sample(),
        "iocs": list(EVERY_TYPE),
        "annotations": ExportAnnotations(),
        "table": TABLE,
    }
    return build_export_input(**{**arguments, **changes})  # type: ignore[arg-type]


def test_the_analysis_facts_are_carried() -> None:
    inputs = build()

    assert inputs.analysis_id == 7
    assert inputs.sample.filename == "invoice.exe"
    assert (inputs.sample.sha256, inputs.sample.md5, inputs.sample.sha1) == (
        SAMPLE_SHA256,
        SAMPLE_MD5,
        SAMPLE_SHA1,
    )
    assert inputs.families == ("emotet",)
    assert inputs.iocs == EVERY_TYPE


def test_techniques_are_distinct_sorted_and_named_from_the_table() -> None:
    assert build().techniques == (
        ExportTechnique("T1059", "Command and Scripting Interpreter"),
        ExportTechnique("T1547.001", "Registry Run Keys / Startup Folder"),
        ExportTechnique("T9999", None),
    )


def test_an_analysis_without_a_summary_has_no_techniques() -> None:
    assert build(analysis=analysis(summary=None)).techniques == ()


def test_the_time_is_when_the_analysis_finished_else_started_else_submitted() -> None:
    started = SUBMITTED + timedelta(minutes=1)
    finished = SUBMITTED + timedelta(minutes=5)

    assert build().observed_at == SUBMITTED
    assert build(analysis=analysis(started_at=started)).observed_at == started
    assert (
        build(analysis=analysis(started_at=started, finished_at=finished)).observed_at == finished
    )


def test_a_time_read_back_without_a_zone_is_taken_as_utc() -> None:
    naive = SUBMITTED.replace(tzinfo=None)

    assert build(analysis=analysis(submitted_at=naive)).observed_at == SUBMITTED


def test_a_missing_sample_row_leaves_md5_and_sha1_out() -> None:
    inputs = build(sample=None)

    assert (inputs.sample.md5, inputs.sample.sha1) == (None, None)
    assert inputs.sample.sha256 == SAMPLE_SHA256


def test_annotations_are_passed_through() -> None:
    annotations = ExportAnnotations(
        tags=("phishing",), notes=(ExportNote("n", TargetType.ANALYSIS, None),)
    )

    assert build(annotations=annotations).annotations == annotations


def tag_on(tag: str, target_type: str, target_ref: str = "", *, orphaned: bool = False) -> dict:
    return {
        "link_id": 1,
        "tag": tag,
        "target_type": target_type,
        "target_ref": target_ref,
        "orphaned": orphaned,
    }


def note_on(body: str, target_type: str, target_ref: str = "", *, orphaned: bool = False) -> dict:
    return {
        "id": 1,
        "body": body,
        "target_type": target_type,
        "target_ref": target_ref,
        "orphaned": orphaned,
        "created_at": SUBMITTED,
        "updated_at": SUBMITTED,
    }


def test_the_export_carries_the_analysis_tags_and_every_note_of_a_live_target() -> None:
    annotations = Annotations.model_validate(
        {
            "tags": [
                tag_on("phishing", "analysis"),
                tag_on("emotet", "analysis"),
                tag_on("noisy", "process", "412"),
            ],
            "notes": [
                note_on("whole run", "analysis"),
                note_on("dropper", "process", "412"),
                note_on("beacon", "event", "ev-1"),
            ],
        }
    )

    exported = export_annotations(annotations)

    assert exported.tags == ("phishing", "emotet")
    assert exported.notes == (
        ExportNote("whole run", TargetType.ANALYSIS, None),
        ExportNote("dropper", TargetType.PROCESS, "412"),
        ExportNote("beacon", TargetType.EVENT, "ev-1"),
    )


def test_an_orphaned_note_stays_out_of_the_export() -> None:
    annotations = Annotations.model_validate(
        {
            "tags": [],
            "notes": [
                note_on("gone", "event", "ev-9", orphaned=True),
                note_on("kept", "event", "ev-1"),
            ],
        }
    )

    assert [note.body for note in export_annotations(annotations).notes] == ["kept"]
