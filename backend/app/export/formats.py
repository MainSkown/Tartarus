import json
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from app.export.csv_export import render_csv
from app.export.inputs import IocExportInput
from app.export.misp import build_event
from app.export.stix import build_bundle


class ExportFormat(StrEnum):
    STIX = "stix"
    MISP = "misp"
    CSV = "csv"

    @property
    def media_type(self) -> str:
        return _SPECS[self].media_type

    @property
    def extension(self) -> str:
        return _SPECS[self].extension


@dataclass(frozen=True)
class _Spec:
    media_type: str
    extension: str
    render: Callable[[IocExportInput], bytes]


def _json_bytes(document: object) -> bytes:
    return json.dumps(document, indent=2, ensure_ascii=False).encode("utf-8")


_SPECS = {
    ExportFormat.STIX: _Spec(
        "application/stix+json;version=2.1",
        "stix.json",
        lambda inputs: _json_bytes(build_bundle(inputs)),
    ),
    ExportFormat.MISP: _Spec(
        "application/json",
        "misp.json",
        lambda inputs: _json_bytes(build_event(inputs)),
    ),
    ExportFormat.CSV: _Spec(
        "text/csv; charset=utf-8",
        "csv",
        lambda inputs: render_csv(inputs).encode("utf-8"),
    ),
}


def render(format_: ExportFormat, inputs: IocExportInput) -> bytes:
    return _SPECS[format_].render(inputs)


def export_filename(analysis_id: int, format_: ExportFormat) -> str:
    return f"tartarus-{analysis_id}-iocs.{format_.extension}"
