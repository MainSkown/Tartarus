from pathlib import Path

from app.rules.rule import Rule, Validity


def make_rule(  # noqa: PLR0913 - one keyword per field a test may vary
    rule_id: str = "11111111-1111-4111-8111-111111111111",
    *,
    title: str = "A rule",
    validity: Validity = Validity.VALID,
    error: str | None = None,
    sha: str = "a" * 64,
    path: str = "/rules/sigma/custom/a.yml",
) -> Rule:
    return Rule(
        id=rule_id,
        title=title,
        description="what it finds",
        level="high",
        status="test",
        tags=("attack.execution",),
        logsource_category="process_creation",
        path=Path(path),
        content_sha256=sha,
        validity=validity,
        error=error,
    )
