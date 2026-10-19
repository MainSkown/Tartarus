from pathlib import Path
from typing import Any

import pytest

from app.ingest.cape_network import CapeNetworkNormalizer
from app.ingest.cape_signatures import CapeSignaturesNormalizer
from app.ingest.capemon import CapemonNormalizer
from app.ingest.defender import DefenderNormalizer
from app.ingest.protocol import IngestContext, Normalizer
from tests.ingest.contract import (
    assert_fields_catalogued,
    check_normalizer_contract,
    check_tolerates_junk,
)
from tests.ingest.defender_cases import (
    DROPPED_STARTED,
    DROPPED_TASK,
    DROPPER_IMAGE,
    context_of,
    copy_export,
    report_of,
)

NORMALIZERS = [
    pytest.param(CapemonNormalizer(), id="capemon"),
    pytest.param(CapeNetworkNormalizer(), id="cape-network"),
    pytest.param(CapeSignaturesNormalizer(), id="cape-signatures"),
]


@pytest.mark.parametrize("normalizer", NORMALIZERS)
def test_normalizer_keeps_the_contract_on_the_full_report(
    normalizer: Normalizer, full_report: dict[str, Any], context: IngestContext
) -> None:
    check_normalizer_contract(normalizer, full_report, context)


@pytest.mark.parametrize("normalizer", NORMALIZERS)
def test_normalizer_does_not_raise_on_a_report_without_its_section(
    normalizer: Normalizer, context: IngestContext
) -> None:
    check_tolerates_junk(normalizer, context)


def test_defender_keeps_the_contract_on_its_export(tmp_path: Path) -> None:
    root = copy_export(tmp_path, "defender-dropped-file.xml")
    report = report_of(DROPPED_TASK, DROPPED_STARTED, (DROPPER_IMAGE,))

    check_normalizer_contract(DefenderNormalizer(), report, context_of(root, DROPPED_STARTED))


def test_defender_tolerates_a_report_without_its_export(context: IngestContext) -> None:
    check_tolerates_junk(DefenderNormalizer(), context)


def test_an_emitted_field_missing_from_the_catalog_fails_the_check() -> None:
    event = {"event": {"id": "0" * 40, "bogus_field": "x"}, "tartarus": {}}

    with pytest.raises(AssertionError, match=r"event\.bogus_field"):
        assert_fields_catalogued([event])
