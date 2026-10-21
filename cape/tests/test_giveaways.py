import base64
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from guest_engine import giveaways
from guest_engine.giveaways import find_giveaway

FACTS_SCRIPT = (
    Path(__file__).parents[2] / "guest" / "profiles" / "windows" / "selftest" / "guest-facts.ps1"
)

GIVEAWAY_CASES = [
    ("tartarus", "tartarus"),
    ("MyTartarusBox", "tartarus"),
    ("sandbox-01", "sandbox"),
    ("SANDBOX", "sandbox"),
    ("malware-lab", "malware"),
    ("virus", "virus"),
    ("myvirus", "virus"),
    ("virus-lab", "virus"),
    ("Antivirus virus", "virus"),
    ("antivirusvirus", "virus"),
    ("Microsoft Defender Antivirus virus", "virus"),
    ("cuckoo", "cuckoo"),
    ("cape", "cape"),
    ("CAPE-01", "cape"),
    ("my-cape-vm", "cape"),
    ("MyCapeVM", "cape"),
    ("cape2", "cape"),
    ("/opt/cape/agent", "cape"),
    ("test", "test"),
    ("Test-PC", "test"),
    ("DesktopTest", "test"),
    ("admin", "admin"),
    ("ADMIN1", "admin"),
    ("analyst", "analy"),
    ("Analysis-box", "analy"),
    ("analyzer", "analy"),
    ("analytics", "analy"),
]

ORDINARY_CASES = [
    "landscape",
    "escape",
    "Capello",
    "capeman",
    "scape",
    "latest",
    "contest",
    "attest",
    "administrator",
    "badminton",
    "Michael",
    "DESKTOP-7A3K2P9",
    "LAPTOP-4Q8R2MZ",
    "analog",
    "canal",
    "",
    "Usługa niejawnego programu testów systemu Windows",
    "Zabezpieczenia urządzenia testowe",
    "antywirusowa",
    "Antywirusowa usługa Microsoft Defender",
    "Microsoft Defender Antivirus Service",
    "Microsoft Defender Antivirus Network Inspection Service",
    "Microsoft Defender Antivirus Network Realtime Inspection",
    "antivirus",
    "ANTIVIRUS",
    "Antivirus",
]


@pytest.mark.parametrize(("text", "word"), GIVEAWAY_CASES)
def test_names_that_say_what_the_machine_is_are_found(text, word):
    assert find_giveaway(text) == word


@pytest.mark.parametrize("text", ORDINARY_CASES)
def test_ordinary_names_and_words_that_merely_contain_a_short_giveaway_pass(text):
    assert find_giveaway(text) is None


def test_a_legitimate_word_is_not_a_giveaway_word():
    assert not any(
        word in legitimate
        for legitimate in giveaways.LEGITIMATE_WORDS
        for word in giveaways.TOKEN_GIVEAWAYS + giveaways.TOKEN_PREFIX_GIVEAWAYS
    )
    assert all(
        any(word in legitimate for word in giveaways.SUBSTRING_GIVEAWAYS)
        for legitimate in giveaways.LEGITIMATE_WORDS
    ), "a legitimate word that contains no giveaway substring is dead weight"


# The guest-side scan cannot import guest_engine.giveaways, so it carries a copy of the lists.

FACTS_PARAMETERS = {
    "SubstringWords": giveaways.SUBSTRING_GIVEAWAYS,
    "TokenWords": giveaways.TOKEN_GIVEAWAYS,
    "PrefixWords": giveaways.TOKEN_PREFIX_GIVEAWAYS,
    "LegitimateWords": giveaways.LEGITIMATE_WORDS,
}


def facts_script_word_lists() -> dict[str, tuple[str, ...]]:
    text = FACTS_SCRIPT.read_text(encoding="utf-8")
    declarations = re.findall(r"\[string\[\]\] \$(\w+Words) = @\(([^)]*)\)", text)
    return {name: tuple(re.findall(r"'([^']*)'", items)) for name, items in declarations}


@pytest.mark.parametrize("name", FACTS_PARAMETERS)
def test_the_facts_script_carries_the_same_word_list_as_the_engine(name):
    assert facts_script_word_lists()[name] == FACTS_PARAMETERS[name]


requires_pwsh = pytest.mark.skipif(
    shutil.which("pwsh") is None,
    reason="pwsh is not installed here; the facts script's rule runs in PowerShell (run it in "
    "mcr.microsoft.com/powershell or on the live guest)",
)


def facts_script_rule() -> str:
    """The word lists, `Split-Tokens` and `Find-Giveaway` of guest-facts.ps1, without the scan
    that follows them (which queries Windows)."""
    text = FACTS_SCRIPT.read_text(encoding="utf-8")
    lists = "".join(
        f"${name} = @({', '.join(repr(word) for word in words)})\n"
        for name, words in facts_script_word_lists().items()
    )
    rule = text[text.index("function Split-Tokens") : text.index("function Write-Giveaway")]
    return lists + rule


def facts_script_answers(texts: list[str]) -> list[str | None]:
    payload = json.dumps(texts).replace("'", "''")
    script = (
        "$ErrorActionPreference = 'Stop'\n"
        + facts_script_rule()
        + f"\n$texts = @(ConvertFrom-Json -InputObject '{payload}')\n"
        + "for ($i = 0; $i -lt $texts.Count; $i++) {\n"
        + "  $found = Find-Giveaway ([string] $texts[$i])\n"
        + '  Write-Output ("{0}:{1}" -f $i, $found)\n'
        + "}\n"
    )
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    result = subprocess.run(  # noqa: S603 - fixed argv, script text from the repo
        ["pwsh", "-NoProfile", "-OutputFormat", "Text", "-EncodedCommand", encoded],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    answers: list[str | None] = [None] * len(texts)
    for line in result.stdout.splitlines():
        index, _, word = line.partition(":")
        answers[int(index)] = word or None
    return answers


@requires_pwsh
def test_the_facts_script_gives_the_same_answer_as_the_engine_for_every_case():
    texts = [text for text, _ in GIVEAWAY_CASES] + ORDINARY_CASES
    assert facts_script_answers(texts) == [find_giveaway(text) for text in texts]
