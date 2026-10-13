from typing import Any

import pytest

from app.ingest.capemon import CapemonNormalizer
from app.ingest.protocol import IngestContext, Normalizer
from tests.ingest.contract import check_normalizer_contract, check_tolerates_junk

NORMALIZERS = [pytest.param(CapemonNormalizer(), id="capemon")]


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
