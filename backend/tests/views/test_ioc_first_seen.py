from typing import Any

from app.schemas.views_findings import IocType
from app.views.iocs import _event_iocs


class FakeIndex:
    def __init__(self, aggregations: dict[str, Any]) -> None:
        self._aggregations = aggregations

    async def search(self, analysis_id: int, body: dict[str, Any]) -> dict[str, Any]:
        return {"aggregations": self._aggregations}


def domain_bucket(*timestamps: str | None) -> dict[str, Any]:
    hits = [
        {
            "_source": {
                **({"@timestamp": stamp} if stamp else {}),
                "event": {"id": f"ev-{n}"},
                "dns": {"question": {"name": "Evil.Example"}},
            }
        }
        for n, stamp in enumerate(timestamps)
    ]
    return {
        "values": {
            "buckets": [
                {"key": "evil.example", "doc_count": len(hits), "events": {"hits": {"hits": hits}}}
            ],
            "sum_other_doc_count": 0,
        }
    }


async def test_an_event_ioc_is_first_seen_when_its_earliest_event_happened() -> None:
    index = FakeIndex(
        {
            "domain": domain_bucket("2026-10-13T12:12:41.383Z", "2026-10-13T12:15:00.000Z"),
        }
    )

    found = await _event_iocs(index, 7)  # type: ignore[arg-type]

    ioc = next(ioc for ioc in found.iocs if ioc.type is IocType.DOMAIN)
    assert ioc.first_seen is not None
    assert ioc.first_seen.isoformat() == "2026-10-13T12:12:41.383000+00:00"


async def test_an_event_without_a_timestamp_leaves_first_seen_empty() -> None:
    index = FakeIndex({"domain": domain_bucket(None)})
    found = await _event_iocs(index, 7)  # type: ignore[arg-type]

    assert [ioc.first_seen for ioc in found.iocs if ioc.type is IocType.DOMAIN] == [None]
