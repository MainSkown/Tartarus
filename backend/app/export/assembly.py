from datetime import UTC, datetime

from app.analyses.summary import ReportSummary
from app.db.models import Analysis, Sample
from app.export.inputs import (
    ExportAnnotations,
    ExportSample,
    ExportTechnique,
    IocExportInput,
)
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
