from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import ConfigDict, Field

from app.db.models.analysis import Severity
from app.schemas.base import ApiModel
from app.schemas.views_events import Listing
from app.search.fields import FieldType, Lane

MAX_CHIPS = 50
MAX_PIDS = 1000
MAX_PAGE_SIZE = 500
DEFAULT_PAGE_SIZE = 100
MAX_FACET_FIELDS = 20
MAX_COLUMNS = 12
DEFAULT_VALUES = 10
MAX_VALUES = 50
DEFAULT_FACET_FIELDS = [
    "process.name",
    "tartarus.lane",
    "event.action",
    "api.name",
    "destination.domain",
    "rule.name",
]

type JsonValue = str | int | float | bool | list[JsonValue] | dict[str, JsonValue] | None
type SortOrder = Literal["@timestamp", "-@timestamp"]


class FilterChip(ApiModel):
    """`field` equal to `value`, or not equal when `negate`; wildcards in the value work as in a
    query."""

    field: str = Field(min_length=1)
    value: str
    negate: bool = False


class TimeRange(ApiModel):
    """Both ends are inclusive; a missing end leaves that side open."""

    model_config = ConfigDict(populate_by_name=True)

    from_: datetime | None = Field(default=None, alias="from")
    to: datetime | None = None


class EventFilter(ApiModel):
    """What narrows the events: the query, the chips, a time range, lanes and pids, all ANDed."""

    query: str = ""
    filters: list[FilterChip] = Field(default_factory=list, max_length=MAX_CHIPS)
    time_range: TimeRange | None = None
    lanes: list[Lane] | None = None
    pids: list[int] | None = Field(default=None, max_length=MAX_PIDS)


class SearchRequest(EventFilter):
    sort: SortOrder = "@timestamp"
    size: int = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)
    search_after: str | None = Field(
        default=None, description="The `next_cursor` of the previous page."
    )
    columns: list[str] = Field(
        default_factory=list,
        max_length=MAX_COLUMNS,
        description="Catalog fields or aliases to return under `fields` of each event, on top of "
        "the typed ones.",
    )


class FacetsRequest(EventFilter):
    fields: list[str] = Field(
        default_factory=lambda: list(DEFAULT_FACET_FIELDS),
        min_length=1,
        max_length=MAX_FACET_FIELDS,
    )


class HistogramRequest(EventFilter):
    interval: Annotated[int, Field(ge=1)] | Literal["auto"] = "auto"


class EventProcess(ApiModel):
    pid: int | None
    name: str | None
    entity_id: str | None


class EventDestination(ApiModel):
    ip: str | None
    port: int | None
    domain: str | None


class Event(ApiModel):
    """The fields the events table shows; `GET events/{id}` has the whole document."""

    id: str
    time: datetime
    sequence: int | None
    lane: str | None
    kind: str | None
    category: list[str]
    action: str | None
    module: str | None
    dataset: str | None
    summary: str | None
    severity: Severity | None
    process: EventProcess | None
    api_name: str | None
    rule_name: str | None
    rule_ruleset: str | None
    destination: EventDestination | None
    dns_query: str | None
    url: str | None
    file_path: str | None
    registry_path: str | None
    fields: dict[str, JsonValue] = Field(
        description="The requested `columns` by canonical field name; a column the event has no "
        "value for is absent."
    )


class EventPage(ApiModel):
    events: list[Event]
    total: int
    next_cursor: str | None


class ValueCount(ApiModel):
    value: str
    count: int


class Facet(ApiModel):
    """`field` is the name as requested; `total` counts the events that have any value for it."""

    field: str
    values: list[ValueCount]
    total: int


class FacetsResponse(ApiModel):
    facets: list[Facet]


class HistogramBucket(ApiModel):
    time: datetime
    total: int
    by_lane: dict[str, int]


class HistogramDetection(ApiModel):
    time: datetime
    id: str
    name: str | None
    severity: Severity | None
    ruleset: str | None


class Histogram(ApiModel):
    """Contiguous buckets from the one holding `from` to the one holding `to`, empty ones
    included. `from` and `to` are null when nothing matches and the filter gives no range."""

    interval_ms: int
    from_: datetime | None = Field(serialization_alias="from")
    to: datetime | None
    total: int
    buckets: list[HistogramBucket]
    detections: list[HistogramDetection]


class RelatedEvents(ApiModel):
    references: Listing[Event]
    referenced_by: Listing[Event]


class EventDetail(ApiModel):
    event: Event
    source: dict[str, Any]
    related: RelatedEvents


class QueryValidateRequest(ApiModel):
    query: str


class QueryErrorRead(ApiModel):
    start: int
    end: int
    message: str
    suggestion: str | None


class QueryValidation(ApiModel):
    ok: bool
    errors: list[QueryErrorRead]


class FieldRead(ApiModel):
    name: str
    type: FieldType
    aliases: list[str]
    description: str
    example: str
    lane: Lane | None
    members: list[str]
    searchable: bool


class ValuesParams(ApiModel):
    field: str = Field(min_length=1, description="A keyword field or alias.")
    prefix: str = Field(default="", description="Matched case-insensitively.")
    limit: int = Field(default=DEFAULT_VALUES, ge=1, le=MAX_VALUES)


class FieldValues(ApiModel):
    values: list[ValueCount]
