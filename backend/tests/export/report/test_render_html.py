import re

import pytest

from app.export.report.assemble import build_report_model
from app.export.report.model import ReportInclude, ReportModel
from app.export.report.render import ReportVariant, render_document, render_html
from app.schemas.views_events import ProcessTree
from app.schemas.views_findings import AttackMatrix, DetectionsView, IocsView, IocType
from tests.export.conftest import make_ioc
from tests.export.report.fixtures import (
    SAMPLE_NAME,
    SAMPLE_SHA256,
    make_analysis,
    make_inputs,
    make_network,
    process,
)
from tests.export.report.support import BREAKOUT, SCRIPT, Page, hostile_model

EVERY_DOMAIN = IocType.DOMAIN
SECTIONS = [
    "summary",
    "notes",
    "attack",
    "process-tree",
    "detections",
    "key-events",
    "network",
    "iocs",
    "screenshots",
]


def iocs_view(iocs: list) -> IocsView:
    return IocsView(iocs=iocs, truncated_types=[])


def model_of(include: ReportInclude | None = None, **changes: object) -> ReportModel:
    return build_report_model(make_inputs(**changes), include or ReportInclude())


def html_of(include: ReportInclude | None = None, **changes: object) -> str:
    return render_html(model_of(include, **changes))


def test_every_section_is_present() -> None:
    page = Page(html_of())

    assert page.ids == [*SECTIONS]


def test_the_header_and_every_section_carry_their_content() -> None:
    text = Page(html_of()).text

    for expected in [
        SAMPLE_NAME,
        SAMPLE_SHA256,
        "emotet",
        "phishing",
        "tlp:amber",
        "T1547.001",
        "Registry Run Keys / Startup Folder",
        "Persistence",
        "Run key written",
        "recon_systeminfo",
        "explorer.exe (100)",
        "summary of cited-0",
        "started cmd.exe",
        "evil.example",
        "203.0.113.7",
        "Global\\Tartarus-Mutex",
        "Looks like an Emotet dropper.",
        "Process invoice.exe (4242)",
        "Event: dns lookup evil.example",
        "13178",
    ]:
        assert expected in text, expected


def test_the_header_says_which_guest_the_sample_was_analysed_on() -> None:
    assert "Analysed on lab1" in Page(html_of()).text


def test_a_report_of_an_analysis_that_records_no_guest_has_no_such_line() -> None:
    options = {"route": "inetsim", "package": "auto", "timeout": 180}

    assert "Analysed on" not in Page(html_of(analysis=make_analysis(options=options))).text


def test_a_severity_is_a_text_label_with_a_class_for_its_colour() -> None:
    html = html_of()

    assert '<span class="sev sev-high">HIGH</span>' in html
    assert '<span class="sev sev-medium">MEDIUM</span>' in html


def test_the_detection_block_says_how_many_cited_events_it_does_not_list() -> None:
    assert "3 more cited events" in Page(html_of()).text


def test_a_detection_names_the_rule_author_and_one_without_prints_nothing() -> None:
    text = Page(html_of()).text

    assert text.count("Rule author:") == 1
    assert "Rule author: Florian Roth" in text


@pytest.mark.parametrize("variant", list(ReportVariant))
def test_the_footer_credits_mitre_attack_with_its_copyright_and_terms(
    variant: ReportVariant,
) -> None:
    text = Page(render_document(model_of(), variant)).text

    assert (
        "© 2026 The MITRE Corporation. This work is reproduced and distributed with the "
        "permission of The MITRE Corporation." in text
    )
    assert "https://attack.mitre.org/resources/legal-and-branding/terms-of-use/" in text


def test_the_key_events_table_says_why_each_event_is_listed() -> None:
    text = Page(html_of()).text

    for reason in ("alert", "process", "file-registry", "cited", "network"):
        assert f" {reason} " in text


def test_the_tree_is_one_svg_in_the_html() -> None:
    assert Page(html_of()).tags.count("svg") == 1


def test_the_report_is_one_document_with_the_dark_theme_and_all_css_inline() -> None:
    html = html_of()

    assert html.lstrip().startswith("<!doctype html>")
    assert html.count("<style>") >= 1
    assert "variant-html" in html
    assert "@page" not in html
    assert re.search(r"--bg:\s*#000000", html)


@pytest.mark.parametrize("variant", list(ReportVariant))
def test_the_document_has_no_reference_to_anything_outside_itself(variant: ReportVariant) -> None:
    html = render_document(model_of(), variant)
    page = Page(html)

    for tag, name, value in page.attributes:
        if name in {"src", "href", "xlink:href", "action", "poster", "data", "srcset"}:
            assert value is not None
            assert value.startswith(("data:", "#")), (tag, name, value[:60])
    assert not {"script", "link", "iframe", "object", "embed", "form", "base"} & set(page.tags)
    assert "@import" not in html
    assert "url(" not in re.sub(r"data:[a-z/]+;base64,[A-Za-z0-9+/=]+", "", html)
    assert not [a for a in page.attributes if a[1].startswith("on")]


def test_the_screenshots_are_embedded_as_data_uris_in_order() -> None:
    page = Page(html_of())

    sources = [value or "" for tag, name, value in page.attributes if (tag, name) == ("img", "src")]
    assert [source.split(";")[0] for source in sources] == ["data:image/png", "data:image/jpeg"]


def test_without_screenshots_the_section_and_every_image_are_gone() -> None:
    html = html_of(ReportInclude(screenshots=False))
    page = Page(html)

    assert "screenshots" not in page.ids
    assert "img" not in page.tags
    assert "data:image" not in html


def test_without_notes_the_section_and_the_notes_are_gone_but_the_tags_stay() -> None:
    html = html_of(ReportInclude(notes=False))
    page = Page(html)

    assert "notes" not in page.ids
    for body in ("Looks like an Emotet dropper.", "Spawns the DNS lookups.", "The beacon"):
        assert body not in html
    assert "phishing" in page.text


def test_without_raw_iocs_a_type_shows_its_count_and_its_first_values_only() -> None:
    many = [make_ioc(EVERY_DOMAIN, f"d{n}.example") for n in range(12)]
    html = html_of(ReportInclude(raw_iocs=False), iocs=iocs_view(many))
    text = Page(html).text

    assert "d0.example" in text
    assert "d4.example" in text
    assert "d5.example" not in text
    assert "d11.example" not in text
    assert "7 more not listed" in text
    assert "first 5 of each type" in text


def test_with_raw_iocs_every_value_is_listed_and_no_sampling_note_appears() -> None:
    many = [make_ioc(EVERY_DOMAIN, f"d{n}.example") for n in range(12)]
    text = Page(html_of(iocs=iocs_view(many))).text

    assert "d11.example" in text
    assert "first 5 of each type" not in text


def test_the_flow_table_lists_no_flow_to_the_sandbox_gateway() -> None:
    text = Page(html_of(network=make_network(flows=2, sandbox_flows=30))).text

    assert "192.168.150.1:443" not in text
    assert "203.0.113.7:443" in text


def test_a_report_with_nothing_to_show_says_so_in_each_section() -> None:
    inputs = make_inputs(
        tree=ProcessTree(roots=[], total=0),
        detections=DetectionsView(groups=[], total=0),
        attack=AttackMatrix(tactics=[], attack_version="16.1"),
        screenshots=[],
        process_events=[],
        file_and_registry_events=[],
        network_events=[],
        note_events={},
    )
    text = Page(render_html(build_report_model(inputs, ReportInclude()))).text

    assert "No screenshots were captured." in text
    assert "No processes were recorded." in text
    assert "No detections." in text


def test_hostile_text_stays_text_everywhere() -> None:
    html = render_html(hostile_model())
    page = Page(html)

    assert SCRIPT not in html
    assert BREAKOUT not in html
    assert "script" not in page.tags
    assert page.tags.count("img") == 2
    assert not [a for a in page.attributes if a[1].startswith("on")]
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert SCRIPT in page.text


def test_hostile_text_stays_text_in_the_print_document_too() -> None:
    html = render_document(hostile_model(), ReportVariant.PDF)
    page = Page(html)

    assert SCRIPT not in html
    assert "script" not in page.tags
    assert page.tags.count("img") == 2
    assert not [a for a in page.attributes if a[1].startswith("on")]


def test_the_print_document_has_page_rules_and_the_light_theme() -> None:
    html = render_document(model_of(), ReportVariant.PDF)

    assert "@page" in html
    assert "variant-pdf" in html
    assert re.search(r"--bg:\s*#ffffff", html)
    assert "#000000" not in html


def test_the_print_document_cuts_a_long_tree_into_windows_of_thirty_rows() -> None:
    wide = process(1, "root.exe", [process(100 + n, f"child{n}.exe") for n in range(70)])
    model = model_of(tree=ProcessTree(roots=[wide], total=71))

    page = Page(render_document(model, ReportVariant.PDF))

    assert page.tags.count("svg") == 3
    assert Page(render_html(model)).tags.count("svg") == 1


def test_both_variants_use_the_same_severity_colours() -> None:
    for variant in ReportVariant:
        html = render_document(model_of(), variant)
        for colour in ("#ef4444", "#f97316", "#eab308", "#94a3b8", "#a3a3a3"):
            assert colour in html


def test_the_print_fonts_are_named() -> None:
    html = render_document(model_of(), ReportVariant.PDF)

    assert "'Liberation Sans'" in html
    assert "'Liberation Mono'" in html
    assert "'DejaVu Sans'" in html


def test_an_unknown_variant_is_refused() -> None:
    with pytest.raises(ValueError, match="not a valid ReportVariant"):
        render_document(model_of(), "docx")  # type: ignore[arg-type]
