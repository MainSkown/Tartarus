import csv
import io
from datetime import UTC, datetime

from app.export.inputs import IocExportInput
from app.schemas.views_events import ProcessRef
from app.schemas.views_findings import Ioc

COLUMNS = ("type", "value", "context", "first_seen", "source_process")
# OWASP's CSV-injection list: a spreadsheet runs a cell that starts with one of these as a formula.
FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")
# A hash from the report or a mutex has no source event, so no time.
NO_FIRST_SEEN = ""


def render_csv(inputs: IocExportInput) -> str:
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(COLUMNS)
    writer.writerows(_row(ioc) for ioc in inputs.distinct_iocs)
    return out.getvalue()


def _row(ioc: Ioc) -> list[str]:
    cells = [
        ioc.type.value,
        ioc.value,
        ioc.context,
        _first_seen_label(ioc.first_seen),
        _process_label(ioc.process),
    ]
    return [_defuse(cell) for cell in cells]


def _first_seen_label(moment: datetime | None) -> str:
    if moment is None:
        return NO_FIRST_SEEN
    return moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _process_label(process: ProcessRef | None) -> str:
    return "" if process is None else f"{process.name or 'unknown'} ({process.pid})"


def _defuse(cell: str) -> str:
    return f"'{cell}" if cell.startswith(FORMULA_STARTS) else cell
