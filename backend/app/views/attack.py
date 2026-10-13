from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from app.analyses.summary import SEVERITY_ORDER
from app.db.models.analysis import Severity
from app.schemas.views_findings import AttackMatrix, AttackTactic, AttackTechniqueHit
from app.search.index import EventIndex
from app.views.alerts import search_alerts
from app.views.attack_table import UNKNOWN_TACTIC, AttackTable
from app.views.event_fields import event_id, int_at, severity_name, texts_at

ALERT_FIELDS = ("event.id", "event.severity", "threat.technique.id")


@dataclass(frozen=True)
class AlertTechniques:
    detection_id: str
    severity: Severity
    technique_ids: tuple[str, ...]


@dataclass
class _Hits:
    detection_ids: list[str]
    severity: Severity


async def attack_matrix(index: EventIndex, analysis_id: int, table: AttackTable) -> AttackMatrix:
    found = await search_alerts(index, analysis_id, ALERT_FIELDS)
    alerts = [
        AlertTechniques(
            event_id(alert),
            severity_name(int_at(alert, "event", "severity") or 0),
            tuple(texts_at(alert, "threat", "technique", "id")),
        )
        for alert in found.alerts
    ]
    return build_matrix(alerts, table)


def build_matrix(alerts: Iterable[AlertTechniques], table: AttackTable) -> AttackMatrix:
    hits = _hits_by_technique(alerts)
    by_tactic: dict[str, list[AttackTechniqueHit]] = defaultdict(list)
    for technique_id, found in sorted(hits.items()):
        info = table.technique(technique_id)
        hit = AttackTechniqueHit(
            id=technique_id,
            name=info.name if info else None,
            hit_count=len(found.detection_ids),
            severity=found.severity,
            detection_ids=found.detection_ids,
        )
        for tactic_id in info.tactics if info and info.tactics else (UNKNOWN_TACTIC,):
            by_tactic[tactic_id].append(hit)
    ordered = [tactic.id for tactic in table.tactics] + [UNKNOWN_TACTIC]
    return AttackMatrix(
        tactics=[
            AttackTactic(
                id=tactic_id, name=table.tactic_name(tactic_id), techniques=by_tactic[tactic_id]
            )
            for tactic_id in ordered
            if tactic_id in by_tactic
        ],
        attack_version=table.version,
    )


def _hits_by_technique(alerts: Iterable[AlertTechniques]) -> dict[str, _Hits]:
    hits: dict[str, _Hits] = {}
    for alert in alerts:
        for technique_id in dict.fromkeys(alert.technique_ids):
            found = hits.setdefault(technique_id, _Hits([], alert.severity))
            found.detection_ids.append(alert.detection_id)
            if SEVERITY_ORDER.index(alert.severity) > SEVERITY_ORDER.index(found.severity):
                found.severity = alert.severity
    return hits
