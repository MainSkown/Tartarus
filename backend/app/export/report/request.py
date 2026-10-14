from app.db.models import Analysis
from app.db.models.analysis import AnalysisStatus
from app.export.report.model import ReportInclude
from app.export.report.render import ReportVariant
from app.schemas.base import ApiModel


class ReportRequest(ApiModel):
    """What a report is asked to be: its file format and the sections it may leave out."""

    format: ReportVariant
    include: ReportInclude = ReportInclude()


class ReportNotPossibleError(Exception):
    """A job's reason for refusing a report; its message is what the analyst reads."""


def reason_not_reportable(analysis: Analysis) -> str | None:
    if analysis.status is AnalysisStatus.DONE:
        return None
    return f"Reports are for finished analyses; analysis {analysis.id} is {analysis.status.value}"
