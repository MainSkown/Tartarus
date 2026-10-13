import pytest

from tests.integration.views.conftest import ViewStack
from tests.integration.views.findings.support import alert
from tests.integration.views.helpers import (
    add_analysis_without_index,
    get_view,
    index_extra_events,
    synthetic_event,
)

pytestmark = pytest.mark.integration

SEVERITY_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


async def test_the_twelve_cape_signatures_are_one_group_sorted_by_severity_then_name(
    stack: ViewStack,
) -> None:
    view = await get_view(stack, "detections")

    assert view["total"] == 12
    assert [group["ruleset"] for group in view["groups"]] == ["cape"]
    detections = view["groups"][0]["detections"]
    ranks = [SEVERITY_RANK[d["severity"]] for d in detections]
    assert ranks == sorted(ranks, reverse=True)
    assert detections[0]["name"] == "recon_systeminfo"
    medium = [d["name"] for d in detections if d["severity"] == "medium"]
    assert medium == sorted(medium)
    assert len(medium) == 7


async def test_a_detection_carries_its_rule_techniques_and_time(stack: ViewStack) -> None:
    view = await get_view(stack, "detections")

    by_name = {d["name"]: d for d in view["groups"][0]["detections"]}
    stealth = by_name["stealth_window"]
    assert stealth["techniques"] == ["T1564.003", "T1564"]
    assert stealth["description"]
    assert stealth["ruleset"] == "cape"
    assert stealth["time"].startswith("2026-10-13T12:12:41")
    assert len(stealth["id"]) == 40


async def test_related_events_resolve_to_existing_events_with_their_process(
    stack: ViewStack,
) -> None:
    view = await get_view(stack, "detections")

    by_name = {d["name"]: d for d in view["groups"][0]["detections"]}
    sideload = by_name["dllload_suspicious_directory"]
    assert sideload["related_event_total"] == 10
    assert len(sideload["related_events"]) == 10
    stored = await stack.index.search(
        stack.analysis_id,
        {
            "size": 10,
            "query": {"terms": {"event.id": [e["id"] for e in sideload["related_events"]]}},
        },
    )
    assert stored["hits"]["total"]["value"] == 10
    first = sideload["related_events"][0]
    assert {"id", "time", "lane", "action", "summary", "process"} <= first.keys()
    assert first["process"]["pid"] == 10116


async def test_a_detection_without_a_process_takes_the_one_of_its_first_related_event(
    stack: ViewStack,
) -> None:
    view = await get_view(stack, "detections")

    by_name = {d["name"]: d for d in view["groups"][0]["detections"]}
    assert by_name["stealth_window"]["process"] == {"pid": 10116, "name": "benign.exe"}
    assert by_name["network_http"]["process"] is None
    assert by_name["network_http"]["related_events"] == []
    assert by_name["network_http"]["related_event_total"] == 0


async def test_related_events_are_capped_at_fifty_but_the_total_is_kept(stack: ViewStack) -> None:
    ids = [f"rel-{n}" for n in range(60)]
    related = [synthetic_event(i, "2026-10-13T12:13:01.000Z", "api-call", "api") for i in ids]
    wide = alert("wide-1", "wide", 3, related={"events": ids})
    await index_extra_events(stack, [*related, wide])

    view = await get_view(stack, "detections")

    wide_detection = next(d for g in view["groups"] for d in g["detections"] if d["name"] == "wide")
    assert wide_detection["related_event_total"] == 60
    assert [e["id"] for e in wide_detection["related_events"]] == ids[:50]


async def test_detections_are_grouped_by_ruleset_in_the_documented_order(
    stack: ViewStack,
) -> None:
    await index_extra_events(
        stack,
        [
            alert("s-1", "Sigma rule", 3, rule={"ruleset": "sigma"}),
            alert("y-1", "yara hit", 4, rule={"ruleset": "yara"}),
            alert("x-1", "other", 1, rule={"ruleset": "zeta"}),
        ],
    )

    view = await get_view(stack, "detections")

    assert [g["ruleset"] for g in view["groups"]] == ["sigma", "cape", "yara", "zeta"]
    assert view["groups"][2]["detections"][0]["severity"] == "critical"


async def test_references_and_the_match_text_are_returned(stack: ViewStack) -> None:
    await index_extra_events(
        stack,
        [
            alert(
                "ref-1",
                "with refs",
                2,
                rule={"ruleset": "cape", "reference": ["https://a.example", "https://b.example"]},
                tartarus={"detection": {"match": "CommandLine contains 'x'"}},
            )
        ],
    )

    view = await get_view(stack, "detections")

    found = next(d for g in view["groups"] for d in g["detections"] if d["name"] == "with refs")
    assert found["references"] == ["https://a.example", "https://b.example"]
    assert found["match"] == "CommandLine contains 'x'"


async def test_an_unknown_analysis_is_a_404_in_the_error_envelope(stack: ViewStack) -> None:
    response = await stack.client.get("/api/analyses/99999/detections")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_an_analysis_without_an_index_has_no_detections(stack: ViewStack) -> None:
    bare = await add_analysis_without_index(stack)

    view = await get_view(stack, "detections", bare)

    assert view == {"groups": [], "total": 0}
