import pytest

from app.rules.attack import attack_fields
from app.rules.loader import load_rules
from tests.rules.support import DEFAULT_RULESET


def test_a_technique_tag_becomes_its_id_in_capitals() -> None:
    assert attack_fields(("attack.t1055", "attack.t1059.001")).techniques == ["T1055", "T1059.001"]


@pytest.mark.parametrize(
    ("tag", "name"),
    [
        ("attack.initial-access", "Initial Access"),
        ("attack.execution", "Execution"),
        ("attack.persistence", "Persistence"),
        ("attack.privilege-escalation", "Privilege Escalation"),
        ("attack.defense-evasion", "Defense Evasion"),
        ("attack.stealth", "Stealth"),
        ("attack.defense-impairment", "Defense Impairment"),
        ("attack.credential-access", "Credential Access"),
        ("attack.discovery", "Discovery"),
        ("attack.lateral-movement", "Lateral Movement"),
        ("attack.collection", "Collection"),
        ("attack.command-and-control", "Command and Control"),
        ("attack.exfiltration", "Exfiltration"),
        ("attack.impact", "Impact"),
        ("attack.resource-development", "Resource Development"),
        ("attack.reconnaissance", "Reconnaissance"),
    ],
)
def test_a_tactic_tag_becomes_its_attack_name(tag: str, name: str) -> None:
    assert attack_fields((tag,)).tactics == [name]


def test_repeats_collapse_and_order_is_kept() -> None:
    fields = attack_fields(
        (
            "attack.t1059",
            "attack.execution",
            "attack.t1059",
            "attack.persistence",
            "attack.execution",
        )
    )

    assert fields.techniques == ["T1059"]
    assert fields.tactics == ["Execution", "Persistence"]


@pytest.mark.parametrize(
    "tag",
    ["attack.g0069", "attack.s0002", "car.2013-05-009", "cve.2020-1234", "detection.dfir", "x"],
)
def test_tags_that_are_neither_techniques_nor_tactics_are_ignored(tag: str) -> None:
    fields = attack_fields((tag,))

    assert fields.techniques == []
    assert fields.tactics == []


def test_every_attack_tag_of_the_shipped_rules_is_understood_or_known_to_be_skipped() -> None:
    tags = {tag for rule in load_rules(DEFAULT_RULESET) for tag in rule.tags}

    unknown = [
        tag
        for tag in sorted(tags)
        if tag.startswith("attack.")
        and not attack_fields((tag,)).techniques
        and not attack_fields((tag,)).tactics
        and not tag.startswith(("attack.g", "attack.s"))
    ]

    assert unknown == []
