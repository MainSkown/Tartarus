import re
from dataclasses import dataclass, field

TECHNIQUE_TAG = re.compile(r"attack\.(t\d{4}(?:\.\d{3})?)", re.IGNORECASE)
TACTIC_PREFIX = "attack."

# Slugs as Sigma tags them. The pinned SigmaHQ commit tags `stealth` and `defense-impairment`
# and has no `defense-evasion` (M4 plan, S0 findings); the classic slug stays for custom rules.
TACTICS = {
    "reconnaissance": "Reconnaissance",
    "resource-development": "Resource Development",
    "initial-access": "Initial Access",
    "execution": "Execution",
    "persistence": "Persistence",
    "privilege-escalation": "Privilege Escalation",
    "defense-evasion": "Defense Evasion",
    "stealth": "Stealth",
    "defense-impairment": "Defense Impairment",
    "credential-access": "Credential Access",
    "discovery": "Discovery",
    "lateral-movement": "Lateral Movement",
    "collection": "Collection",
    "command-and-control": "Command and Control",
    "exfiltration": "Exfiltration",
    "impact": "Impact",
}


@dataclass(frozen=True)
class AttackFields:
    techniques: list[str] = field(default_factory=list)
    tactics: list[str] = field(default_factory=list)


def attack_fields(tags: tuple[str, ...]) -> AttackFields:
    """`threat.technique.id` and `threat.tactic.name` values from a rule's `attack.*` tags.

    Group, software and non-ATT&CK tags (`attack.g0069`, `car.*`) name no technique or tactic
    and are skipped.
    """
    techniques: dict[str, None] = {}
    tactics: dict[str, None] = {}
    for tag in tags:
        if match := TECHNIQUE_TAG.fullmatch(tag):
            techniques[match.group(1).upper()] = None
        elif tag.lower().startswith(TACTIC_PREFIX) and (
            name := TACTICS.get(tag.lower().removeprefix(TACTIC_PREFIX))
        ):
            tactics[name] = None
    return AttackFields(list(techniques), list(tactics))
