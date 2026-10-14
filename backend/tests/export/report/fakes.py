"""An event index that answers the searches the report gatherer makes, from event documents."""

from typing import Any


def source_doc(
    event_id: str, lane: str, summary: str, second: int = 1, **sections: Any
) -> dict[str, Any]:
    return {
        "@timestamp": f"2026-10-13T12:00:{second:02d}Z",
        "event": {"id": event_id, "sequence": second, "action": "act", "kind": "event"},
        "tartarus": {"lane": lane, "summary": summary},
        "process": {"pid": 4242, "name": "invoice.exe", "entity_id": "x"},
        **sections,
    }


def hits_response(docs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "hits": {
            "total": {"value": len(docs)},
            "hits": [{"_id": d["event"]["id"], "_source": d} for d in docs],
        }
    }


DOCS = [
    source_doc("proc-1", "process", "started cmd.exe", 3),
    source_doc("file-1", "file", "created stage2.dll", 5),
    source_doc("reg-1", "registry", "set Run key", 6),
    source_doc("net-1", "network", "connect", 7, destination={"ip": "203.0.113.7"}),
    source_doc("net-2", "network", "connect again", 8, destination={"ip": "203.0.113.7"}),
    source_doc("api-1", "api", "NtCreateFile", 9),
    source_doc("ev-dns", "network", "dns lookup evil.example", 10),
]


class FakeIndex:
    """Answers a lane search, an id search and the process-presence aggregation of the orphan
    check; every body it receives is kept.
    """

    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self.docs = docs
        self.bodies: list[dict[str, Any]] = []

    async def search(
        self, analysis_id: int, body: dict[str, Any], request_timeout: float | None = None
    ) -> dict[str, Any]:
        self.bodies.append(body)
        query = body.get("query", {})
        if "aggs" in body:
            pids = query["bool"]["filter"][1]["terms"]["process.pid"]
            buckets = [{"key": pid} for pid in pids if pid == 4242]
            return {"hits": {"hits": []}, "aggregations": {"present": {"buckets": buckets}}}
        if "ids" in query:
            wanted = set(query["ids"]["values"])
            return hits_response([d for d in self.docs if d["event"]["id"] in wanted])
        lanes = query["bool"]["filter"][0]["terms"]["tartarus.lane"]
        found = [d for d in self.docs if d["tartarus"]["lane"] in lanes]
        return hits_response(found[: body["size"]])

    def lane_queries(self) -> list[dict[str, Any]]:
        return [b for b in self.bodies if "bool" in b.get("query", {}) and "aggs" not in b]

    def id_queries(self) -> list[dict[str, Any]]:
        return [b for b in self.bodies if "ids" in b.get("query", {})]
