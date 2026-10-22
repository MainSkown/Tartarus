import json
from typing import Any

MAX_RAW_BYTES = 1024**2


def with_capped_raw(event: dict[str, Any]) -> dict[str, Any]:
    """The event, or a copy whose ``tartarus.raw`` is a note of its size when it exceeds the cap.

    One record of a few hundred megabytes would otherwise push its bulk request past OpenSearch's
    ``http.max_content_length`` and fail every event sharing it.
    """
    tartarus = event.get("tartarus")
    if not isinstance(tartarus, dict) or (raw := tartarus.get("raw")) is None:
        return event
    size = len(json.dumps(raw, default=str))
    if size <= MAX_RAW_BYTES:
        return event
    return {**event, "tartarus": {**tartarus, "raw": {"truncated": True, "original_bytes": size}}}
