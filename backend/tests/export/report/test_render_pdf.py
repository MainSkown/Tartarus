import asyncio
import io
import threading
import time
from typing import Any

import pypdf
import pytest

from app.export.report import render
from app.export.report.assemble import build_report_model
from app.export.report.model import ReportInclude, ReportModel
from app.export.report.render import render_pdf, render_pdf_off_loop
from app.schemas.views_events import ProcessTree
from tests.export.report.fixtures import SAMPLE_NAME, facts, make_inputs, process
from tests.export.report.support import SCRIPT, hostile_model

pytest.importorskip(
    "weasyprint", reason="WeasyPrint needs Pango; run these tests inside the backend image"
)


def model_of(include: ReportInclude | None = None, **changes: object) -> ReportModel:
    return build_report_model(make_inputs(**changes), include or ReportInclude())


def read(pdf: bytes) -> pypdf.PdfReader:
    return pypdf.PdfReader(io.BytesIO(pdf))


def text_of(reader: pypdf.PdfReader) -> str:
    return " ".join(" ".join(page.extract_text().split()) for page in reader.pages)


def image_count(reader: pypdf.PdfReader) -> int:
    """WeasyPrint lists every image in each page's resources, so the pages share names."""
    return len({image.name for page in reader.pages for image in page.images})


@pytest.fixture(scope="module")
def default_pdf() -> bytes:
    return render_pdf(model_of())


def test_the_pdf_opens_as_a_few_a4_pages(default_pdf: bytes) -> None:
    reader = read(default_pdf)

    assert default_pdf.startswith(b"%PDF-")
    assert 2 <= len(reader.pages) <= 8
    assert {round(float(box)) for box in reader.pages[0].mediabox[2:]} == {595, 842}


def test_the_pdf_titles_itself_after_the_sample(default_pdf: bytes) -> None:
    title = read(default_pdf).metadata.title or ""

    assert SAMPLE_NAME in title
    assert "analysis #7" in title


def test_the_pdf_text_has_the_sample_the_note_and_the_findings(default_pdf: bytes) -> None:
    text = text_of(read(default_pdf))

    for expected in [
        SAMPLE_NAME,
        "Looks like an Emotet dropper.",
        "Run key written",
        "T1547.001",
        "evil.example",
        "explorer.exe (100)",
        "phishing",
    ]:
        assert expected in text, expected


def test_every_page_has_a_footer_with_the_analysis_and_a_page_number(default_pdf: bytes) -> None:
    reader = read(default_pdf)
    pages = len(reader.pages)

    for number, page in enumerate(reader.pages, start=1):
        text = " ".join(page.extract_text().split())
        assert "Tartarus analysis #7" in text
        assert f"page {number} / {pages}" in text


def test_the_screenshots_are_images_in_the_pdf(default_pdf: bytes) -> None:
    assert image_count(read(default_pdf)) == 2


def test_without_the_screenshots_option_the_pdf_holds_no_image() -> None:
    pdf = render_pdf(model_of(ReportInclude(screenshots=False)))

    assert image_count(read(pdf)) == 0


def test_without_the_notes_option_the_note_is_not_in_the_pdf() -> None:
    text = text_of(read(render_pdf(model_of(ReportInclude(notes=False)))))

    assert "Looks like an Emotet dropper." not in text
    assert SAMPLE_NAME in text


def test_a_long_tree_prints_in_windows_that_keep_the_text_readable() -> None:
    wide = process(1, "root.exe", [process(100 + n, f"child{n}.exe") for n in range(100)])
    reader = read(render_pdf(model_of(tree=ProcessTree(roots=[wide], total=101))))
    text = text_of(reader)

    assert len(reader.pages) >= 5
    assert "child0.exe (100)" in text
    assert "child99.exe (199)" in text


def test_the_pdf_links_to_nothing_and_runs_nothing() -> None:
    pdf = render_pdf(hostile_model())

    for marker in (b"/URI", b"/JavaScript", b"/JS", b"/Launch", b"/OpenAction"):
        assert marker not in pdf


def test_hostile_text_prints_as_text() -> None:
    text = text_of(read(render_pdf(hostile_model())))

    assert SCRIPT in text


def test_the_pdf_refuses_to_fetch_anything_but_embedded_data() -> None:
    fetcher = render.embedded_only_fetcher()

    with pytest.raises(ValueError, match="disallowed"):
        fetcher.fetch("file:///etc/hostname")
    with pytest.raises(ValueError, match="disallowed"):
        fetcher.fetch("http://127.0.0.1:9/x.png")
    assert fetcher.fetch("data:text/plain;base64,aGk=") is not None


async def test_rendering_off_the_loop_returns_the_same_pdf_in_a_worker_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[threading.Thread] = []

    def slow_render(model: ReportModel) -> bytes:
        seen.append(threading.current_thread())
        time.sleep(0.3)
        return b"%PDF-fake"

    monkeypatch.setattr(render, "render_pdf", slow_render)
    ticks = 0

    async def tick() -> None:
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    ticker = asyncio.create_task(tick())
    pdf = await render.render_pdf_off_loop(model_of())
    ticker.cancel()

    assert pdf == b"%PDF-fake"
    assert seen[0] is not threading.main_thread()
    assert ticks >= 10


async def test_the_off_loop_render_of_a_real_model_is_a_pdf() -> None:
    assert (await render_pdf_off_loop(model_of())).startswith(b"%PDF-")


def printed_words(model: ReportModel) -> set[str]:
    """Every run of text WeasyPrint laid out on one line of one page, as the PDF will hold it."""
    from weasyprint import HTML  # noqa: PLC0415 -- the module skips when Pango is missing

    document = HTML(
        string=render.render_document(model, render.ReportVariant.PDF),
        url_fetcher=render.embedded_only_fetcher(),
    ).render()
    words: set[str] = set()

    def walk(box: Any) -> None:
        if getattr(box, "text", None):
            words.add(box.text.strip())
        for child in getattr(box, "children", ()):
            walk(child)

    for page in document.pages:
        walk(page._page_box)
    return words


def crowded_model() -> ReportModel:
    long_summary = (
        "Created C:\\Users\\Analyst\\AppData\\Roaming\\Microsoft\\Windows\\Recent\\" + "x" * 60
    )
    pools = [
        facts(f"file-{n}", 5 + n, "file", long_summary, process_name="WmiPrvSE.exe", pid=7144)
        for n in range(6)
    ]
    return model_of(file_and_registry_events=pools)


def test_a_short_word_in_a_narrow_column_is_not_broken_across_lines() -> None:
    """The Why, Lane and Process cells hold short words that must stay whole."""
    words = printed_words(crowded_model())

    for whole in ("file-registry", "process"):
        assert whole in words
    assert {word.split(" ")[0] for word in words if "WmiPrvSE" in word} == {"WmiPrvSE.exe"}


def test_the_screenshots_heading_is_never_left_alone_at_the_foot_of_a_page() -> None:
    reader = read(render_pdf(model_of()))

    for page in reader.pages:
        words = page.extract_text().split()
        if "Screenshots" in words:
            assert "Screenshot" in words
            assert "1" in words


def test_the_print_stylesheet_uses_nothing_weasyprint_has_to_ignore(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("WARNING", logger="weasyprint"):
        render_pdf(model_of())

    assert [record.getMessage() for record in caplog.records] == []
