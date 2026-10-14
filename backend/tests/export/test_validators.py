import copy

import pytest
import stix2

from tests.export.validation import misp_problems, parse_stix

VALID_MISP = {
    "Event": {
        "info": "x",
        "uuid": "11111111-1111-5111-8111-111111111111",
        "date": "2026-10-13",
        "timestamp": "1760358615",
        "Tag": [{"name": "tlp:amber"}],
        "Attribute": [
            {
                "type": "domain",
                "category": "Network activity",
                "value": "a.example",
                "to_ids": True,
                "uuid": "22222222-2222-5222-8222-222222222222",
                "timestamp": "1760358615",
            }
        ],
    }
}


def test_the_stix_parser_rejects_a_bundle_with_a_broken_indicator() -> None:
    broken = {
        "type": "bundle",
        "id": "bundle--11111111-1111-4111-8111-111111111111",
        "objects": [
            {
                "type": "indicator",
                "spec_version": "2.1",
                "id": "indicator--22222222-2222-4222-8222-222222222222",
                "created": "2026-10-13T12:30:15.250Z",
                "modified": "2026-10-13T12:30:15.250Z",
                "pattern": "[domain-name:value = ",
                "pattern_type": "stix",
                "valid_from": "2026-10-13T12:30:15.250Z",
            }
        ],
    }

    with pytest.raises(stix2.exceptions.STIXError):
        parse_stix(broken)


def test_the_misp_check_accepts_a_minimal_valid_event() -> None:
    assert misp_problems(VALID_MISP) == []


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("Event", "Attribute", 0, "to_ids"), "true"),
        (("Event", "Attribute", 0, "timestamp"), 1760358615),
        (("Event", "Attribute", 0, "category"), "Persistence mechanism"),
        (("Event", "Attribute", 0, "uuid"), "not-a-uuid"),
        (("Event", "surprise"), "x"),
        (("Event", "Tag", 0, "title"), "tlp:amber"),
    ],
)
def test_the_misp_check_rejects_a_broken_event(path: tuple[str | int, ...], value: object) -> None:
    broken = copy.deepcopy(VALID_MISP)
    target = broken
    for key in path[:-1]:
        target = target[key]  # type: ignore[index]
    target[path[-1]] = value  # type: ignore[index]

    assert misp_problems(broken)


def test_the_misp_check_rejects_an_event_without_info() -> None:
    broken = copy.deepcopy(VALID_MISP)
    del broken["Event"]["info"]

    assert misp_problems(broken)
