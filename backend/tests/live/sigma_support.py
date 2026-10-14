from pathlib import Path

from tests.rules.support import rule_yaml, simple_detection

# One rule per Sigma category the fixture run (live_logs_45) has events for.
FIXTURE_RULES = (
    ("Ver", "process_creation", "CommandLine|contains: /c ver"),
    ("Benign file", "file_event", "TargetFilename|endswith: tartarus-benign.txt"),
    ("Benign key", "registry_add", "TargetObject|endswith: \\Software\\Tartarus"),
    ("Benign dns", "dns_query", "QueryName|endswith: .example"),
)


def write_rules(directory: Path) -> Path:
    """Writes the `FIXTURE_RULES` as files, each with its own id; returns the directory."""
    directory.mkdir(parents=True, exist_ok=True)
    for number, (title, category, selection) in enumerate(FIXTURE_RULES, start=1):
        text = rule_yaml(
            simple_detection(selection),
            category=category,
            title=title,
            rule_id=f"00000000-0000-4000-8000-{number:012d}",
            level="medium",
            tags=("attack.discovery",),
        )
        (directory / f"rule-{number}.yml").write_text(text, encoding="utf-8")
    return directory
