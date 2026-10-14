from app.rules.rule import Validity
from app.schemas.base import ApiModel


class RuleRead(ApiModel):
    id: str
    title: str
    description: str | None
    level: str | None
    status: str | None
    tags: list[str]
    logsource_category: str | None
    validity: Validity
    error: str | None
    enabled: bool
    path: str
    hits: int


class RuleDetail(RuleRead):
    yaml: str


class RuleEnabledUpdate(ApiModel):
    enabled: bool


class RuleHit(ApiModel):
    rule_id: str
    count: int
