from datetime import datetime

import pytest

from app.export.inputs import ExportAnnotations
from app.schemas.views_findings import IocType
from tests.export.conftest import DROPPED_SHA256, SAMPLE_SHA256, make_ioc


def test_hashes_seen_twice_are_one_indicator(make_input) -> None:
    sample_again = make_ioc(IocType.HASH, SAMPLE_SHA256.upper(), "Payload again")
    inputs = make_input(
        iocs=(
            make_ioc(IocType.HASH, SAMPLE_SHA256, "Submitted sample"),
            sample_again,
            make_ioc(IocType.HASH, DROPPED_SHA256, "Dropped file"),
        )
    )

    values = [ioc.value for ioc in inputs.distinct_iocs]

    assert values == [SAMPLE_SHA256, DROPPED_SHA256]


def test_a_value_of_another_type_is_not_a_duplicate(make_input) -> None:
    inputs = make_input(
        iocs=(make_ioc(IocType.DOMAIN, "a.example"), make_ioc(IocType.URL, "a.example"))
    )

    assert len(inputs.distinct_iocs) == 2


def test_the_tlp_tag_is_the_analysts_when_there_is_one() -> None:
    assert ExportAnnotations(tags=("phishing", "tlp:red")).tlp_tag == "tlp:red"
    assert ExportAnnotations(tags=("phishing",)).tlp_tag is None
    assert ExportAnnotations(tags=("tlp:green", "tlp:amber")).tlp_tag == "tlp:amber"


def test_the_first_of_two_duplicates_keeps_its_place(make_input) -> None:
    inputs = make_input(
        iocs=(
            make_ioc(IocType.DOMAIN, "a.example"),
            make_ioc(IocType.DOMAIN, "b.example"),
            make_ioc(IocType.DOMAIN, "A.example"),
        )
    )

    assert [ioc.value for ioc in inputs.distinct_iocs] == ["a.example", "b.example"]


def test_a_time_without_a_zone_is_refused(make_input) -> None:
    with pytest.raises(ValueError, match="timezone"):
        make_input(observed_at=datetime(2026, 10, 13, 12, 0))
