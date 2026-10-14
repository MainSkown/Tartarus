"""The report model as an HTML file or a PDF, from one template."""

import asyncio
from datetime import UTC, datetime
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from markupsafe import Markup

from app.export.report.assemble import IOC_SAMPLE_PER_TYPE
from app.export.report.key_events import MAX_KEY_EVENTS
from app.export.report.model import ReportModel
from app.export.report.process_tree_svg import (
    MAX_DEPTH,
    MAX_ROWS,
    PRINT_PALETTE,
    SCREEN_PALETTE,
    TreeDrawing,
    TreePalette,
)
from app.export.report.theme import PRINT_FONTS, SCREEN_FONTS, SEVERITY_COLOURS, FontStacks
from app.schemas.views_findings import IocType

TEMPLATE_DIRECTORY = Path(__file__).parent / "templates"
TEMPLATE_NAME = "report.html.j2"
SECONDS_PER_MINUTE = 60
IOC_LABELS = {
    IocType.HASH: "Hashes",
    IocType.DOMAIN: "Domains",
    IocType.IP: "IP addresses",
    IocType.URL: "URLs",
    IocType.MUTEX: "Mutexes",
    IocType.REGISTRY: "Registry paths",
    IocType.FILE: "File paths",
}


class ReportVariant(StrEnum):
    HTML = "html"
    PDF = "pdf"


def render_html(model: ReportModel) -> str:
    """One self-contained file in the dark Tartarus theme; it references nothing outside itself."""
    return render_document(model, ReportVariant.HTML)


def render_pdf(model: ReportModel) -> bytes:
    """The print variant of the same document as a PDF.

    Blocking: it holds the event loop for the whole render (about 3 s for a typical report), so
    async code calls `render_pdf_off_loop`.
    """
    from weasyprint import HTML  # noqa: PLC0415 -- the HTML report needs no Pango

    document = render_document(model, ReportVariant.PDF)
    return HTML(string=document, url_fetcher=embedded_only_fetcher()).write_pdf() or b""


async def render_pdf_off_loop(model: ReportModel) -> bytes:
    return await asyncio.to_thread(render_pdf, model)


@lru_cache
def embedded_only_fetcher() -> Any:
    """Resolves `data:` URIs and refuses everything else, so no text in a report can make the
    renderer read a local file or call out.
    """
    from weasyprint import URLFetcher  # noqa: PLC0415

    return URLFetcher(allowed_protocols={"data"})


def render_document(model: ReportModel, variant: ReportVariant) -> str:
    variant = ReportVariant(variant)
    printed = variant is ReportVariant.PDF
    palette = PRINT_PALETTE if printed else SCREEN_PALETTE
    return (
        _environment()
        .get_template(TEMPLATE_NAME)
        .render(
            model=model,
            variant=variant.value,
            tokens=Markup(_tokens(PRINT_FONTS if printed else SCREEN_FONTS)),  # noqa: S704
            stylesheet=Markup(_stylesheet(variant)),  # noqa: S704
            tree_svgs=_tree_svgs(model, palette, windowed=printed),
            max_tree_rows=MAX_ROWS,
            max_tree_depth=MAX_DEPTH,
            max_key_events=MAX_KEY_EVENTS,
            ioc_sample=IOC_SAMPLE_PER_TYPE,
            ioc_labels={type_.value: label for type_, label in IOC_LABELS.items()},
        )
    )


def _tree_svgs(model: ReportModel, palette: TreePalette, *, windowed: bool) -> list[Markup]:
    if not model.process_tree:
        return []
    drawing = TreeDrawing(model.process_tree, palette)
    pieces = drawing.windows() if windowed else [drawing.svg()]
    return [Markup(piece) for piece in pieces]  # noqa: S704 -- ElementTree escaped every string


def _tokens(fonts: FontStacks) -> str:
    severities = "".join(
        f"--{severity.value}: {colour};" for severity, colour in SEVERITY_COLOURS.items()
    )
    return f":root {{ {severities} --font-sans: {fonts.sans}; --font-mono: {fonts.mono}; }}"


@lru_cache
def _stylesheet(variant: ReportVariant) -> str:
    theme = "print.css" if variant is ReportVariant.PDF else "screen.css"
    return "\n".join((TEMPLATE_DIRECTORY / name).read_text() for name in ("base.css", theme))


@lru_cache
def _environment() -> Environment:
    environment = Environment(
        loader=FileSystemLoader(TEMPLATE_DIRECTORY),
        autoescape=True,
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    environment.filters["stamp"] = _stamp
    environment.filters["clock"] = _clock
    environment.filters["duration"] = _duration
    return environment


def _stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def _clock(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%H:%M:%S.%f")[:-3]


def _duration(seconds: int) -> str:
    minutes, rest = divmod(seconds, SECONDS_PER_MINUTE)
    return f"{minutes} min {rest:02d} s" if minutes else f"{rest} s"
