from datetime import UTC, datetime

from app.analyses.summary import ReportSummary
from app.db.models import Analysis, Sample
from app.db.models.annotation import TargetType as StoredTargetType
from app.export.inputs import (
    ExportAnnotations,
    ExportNote,
    ExportSample,
    ExportTechnique,
    IocExportInput,
    TargetType,
)
from app.schemas.annotations import Annotations
from app.schemas.views_findings import Ioc
from app.views.attack_table import AttackTable


def build_export_input(
    analysis: Analysis,
    sample: Sample | None,
    iocs: list[Ioc],
    annotations: ExportAnnotations,
    table: AttackTable,
) -> IocExportInput:
    return IocExportInput(
        analysis_id=analysis.id,
        sample=ExportSample(
            filename=analysis.filename,
            sha256=analysis.sample_sha256,
            md5=sample.md5 if sample else None,
            sha1=sample.sha1 if sample else None,
        ),
        observed_at=_observed_at(analysis),
        iocs=tuple(iocs),
        families=tuple(analysis.detected_families),
        techniques=_techniques(analysis, table),
        annotations=annotations,
    )


def _observed_at(analysis: Analysis) -> datetime:
    moment = analysis.finished_at or analysis.started_at or analysis.submitted_at
    # SQLite, which the unit tests use, hands datetimes back without their zone.
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _techniques(analysis: Analysis, table: AttackTable) -> tuple[ExportTechnique, ...]:
    if analysis.summary is None:
        return ()
    summary = ReportSummary.model_validate(analysis.summary)
    return tuple(
        ExportTechnique(
            technique_id, info.name if (info := table.technique(technique_id)) else None
        )
        for technique_id in sorted({technique.id for technique in summary.techniques})
    )


def export_annotations(annotations: Annotations) -> ExportAnnotations:
    """Only the analysis's own tags, since the formats have no place for a process's or an
    event's tag, and no note whose target is gone from the index.
    """
    return ExportAnnotations(
        tags=tuple(
            tag.tag for tag in annotations.tags if tag.target_type is StoredTargetType.ANALYSIS
        ),
        notes=tuple(
            ExportNote(
                note.body,
                TargetType(note.target_type),
                note.target_ref or None,
            )
            for note in annotations.notes
            if not note.orphaned
        ),
    )
