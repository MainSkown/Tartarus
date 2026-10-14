"""The searches of `POST events/histogram` and the histogram their responses become."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.events.execution import SEARCH_TIMEOUT
from app.events.filters import epoch_millis, filter_query
from app.events.search import OLDEST_FIRST
from app.schemas.events_api import (
    Histogram,
    HistogramBucket,
    HistogramDetection,
    HistogramRequest,
)
from app.views.event_fields import Source, event_id, event_time, int_at, severity_name, text_at

SECOND = 1000
MINUTE = 60 * SECOND
HOUR = 60 * MINUTE
DAY = 24 * HOUR
NICE_INTERVALS_MS = (
    *(1, 2, 5, 10, 20, 50, 100, 200, 500),
    *(n * SECOND for n in (1, 2, 5, 10, 15, 30)),
    *(n * MINUTE for n in (1, 2, 5, 10, 15, 30)),
    *(n * HOUR for n in (1, 2, 3, 6, 12)),
    *(n * DAY for n in (1, 2, 7, 14, 30)),
)
AUTO_BUCKETS = 120
MAX_BUCKETS = 2000
MAX_DETECTIONS = 500
LANE_VALUES = 20
UNKNOWN_LANE = "unknown"
ALERT = {"term": {"event.kind": "alert"}}
DETECTION_FIELDS = ["@timestamp", "event.id", "event.severity", "rule.name", "rule.ruleset"]


@dataclass(frozen=True, slots=True)
class Extent:
    """The times of the first and last event the filter keeps, in epoch milliseconds."""

    start_ms: int | None
    end_ms: int | None


@dataclass(frozen=True, slots=True)
class HistogramPlan:
    interval_ms: int
    start_ms: int | None
    end_ms: int | None

    def bucket_keys(self) -> range:
        """The start of every bucket from the one holding the start to the one holding the end."""
        if self.start_ms is None or self.end_ms is None or self.start_ms > self.end_ms:
            return range(0)
        first = self.start_ms // self.interval_ms * self.interval_ms
        return range(first, self.end_ms + 1, self.interval_ms)


def bucket_count(start_ms: int, end_ms: int, interval_ms: int) -> int:
    """How many buckets of `interval_ms`, aligned to the epoch, hold the range."""
    return end_ms // interval_ms - start_ms // interval_ms + 1


def plan_histogram(request: HistogramRequest, extent: Extent) -> HistogramPlan:
    """The span is the request's time range where it gives an end, else the events' own.

    `auto` is the smallest of the nice intervals that makes at most 120 buckets; an explicit
    interval is widened just enough to stay within 2000.
    """
    start, end = _span(request, extent)
    requested = request.interval
    if start is None or end is None or start > end:
        return HistogramPlan(1000 if requested == "auto" else requested, start, end)
    interval = _auto_interval(start, end) if requested == "auto" else requested
    return HistogramPlan(max(interval, _narrowest_within_limit(start, end)), start, end)


def _span(request: HistogramRequest, extent: Extent) -> tuple[int | None, int | None]:
    time_range = request.time_range
    start = epoch_millis(time_range.from_) if time_range and time_range.from_ else extent.start_ms
    end = epoch_millis(time_range.to) if time_range and time_range.to else extent.end_ms
    return start, end


def _auto_interval(start_ms: int, end_ms: int) -> int:
    for interval in NICE_INTERVALS_MS:
        if bucket_count(start_ms, end_ms, interval) <= AUTO_BUCKETS:
            return interval
    return NICE_INTERVALS_MS[-1]


def _narrowest_within_limit(start_ms: int, end_ms: int) -> int:
    """A range of `n` intervals touches at most n + 2 buckets, so n <= MAX_BUCKETS - 2 suffices."""
    return (end_ms - start_ms) // (MAX_BUCKETS - 2) + 1


def extent_body(request: HistogramRequest) -> dict[str, Any]:
    return {
        "query": filter_query(request),
        "size": 0,
        "track_total_hits": False,
        "timeout": SEARCH_TIMEOUT,
        "aggs": {
            "first": {"min": {"field": "@timestamp"}},
            "last": {"max": {"field": "@timestamp"}},
        },
    }


def read_extent(response: Mapping[str, Any]) -> Extent:
    aggregations: Mapping[str, Any] = response.get("aggregations", {})
    first = aggregations.get("first", {}).get("value")
    last = aggregations.get("last", {}).get("value")
    return Extent(None if first is None else int(first), None if last is None else int(last))


def histogram_body(request: HistogramRequest, plan: HistogramPlan) -> dict[str, Any]:
    return {
        "query": filter_query(request),
        "size": 0,
        "track_total_hits": True,
        "timeout": SEARCH_TIMEOUT,
        "aggs": {
            "over_time": {
                "date_histogram": {
                    "field": "@timestamp",
                    "fixed_interval": f"{plan.interval_ms}ms",
                    "min_doc_count": 1,
                },
                "aggs": {
                    "lanes": {
                        "terms": {
                            "field": "tartarus.lane",
                            "size": LANE_VALUES,
                            "missing": UNKNOWN_LANE,
                        }
                    }
                },
            }
        },
    }


def read_histogram(
    plan: HistogramPlan, response: Mapping[str, Any], detections: list[HistogramDetection]
) -> Histogram:
    return Histogram(
        interval_ms=plan.interval_ms,
        from_=_moment(plan.start_ms),
        to=_moment(plan.end_ms),
        total=int(response["hits"]["total"]["value"]),
        buckets=_contiguous_buckets(plan, response),
        detections=detections,
    )


def _contiguous_buckets(plan: HistogramPlan, response: Mapping[str, Any]) -> list[HistogramBucket]:
    found = {
        int(bucket["key"]): bucket
        for bucket in response.get("aggregations", {}).get("over_time", {}).get("buckets", [])
    }
    return [_bucket(key, found.get(key)) for key in plan.bucket_keys()]


def _bucket(key: int, found: Mapping[str, Any] | None) -> HistogramBucket:
    if found is None:
        return HistogramBucket(time=_utc(key), total=0, by_lane={})
    by_lane = {lane["key"]: lane["doc_count"] for lane in found["lanes"]["buckets"]}
    return HistogramBucket(time=_utc(key), total=found["doc_count"], by_lane=by_lane)


def _moment(epoch_ms: int | None) -> datetime | None:
    return None if epoch_ms is None else _utc(epoch_ms)


def _utc(epoch_ms: int) -> datetime:
    return datetime.fromtimestamp(epoch_ms / 1000, tz=UTC)


def detections_body(request: HistogramRequest) -> dict[str, Any]:
    return {
        "query": {"bool": {"filter": [filter_query(request), ALERT]}},
        "size": MAX_DETECTIONS,
        "sort": OLDEST_FIRST,
        "track_total_hits": False,
        "timeout": SEARCH_TIMEOUT,
        "_source": DETECTION_FIELDS,
    }


def read_detections(response: Mapping[str, Any]) -> list[HistogramDetection]:
    return [_detection(hit["_source"]) for hit in response["hits"]["hits"]]


def _detection(source: Source) -> HistogramDetection:
    severity = int_at(source, "event", "severity")
    return HistogramDetection(
        time=event_time(source),
        id=event_id(source),
        name=text_at(source, "rule", "name"),
        severity=None if severity is None else severity_name(severity),
        ruleset=text_at(source, "rule", "ruleset"),
    )
