"""Every supervised program starts with the secrets it reads and no others (C2 F6).

supervisord hands each child the environment it started with, so a bug in a network-facing or
hostile-data parser (guacd, gunicorn, the processor, Volatility) would otherwise leak the control
token, the CAPE API token and the database password in one read of /proc/self/environ.
"""

import configparser
import os
import re
import subprocess
from pathlib import Path

import pytest

CAPE = Path(__file__).resolve().parents[1]
WRAPPER = CAPE / "bin" / "keep-secrets"
SECRETS = {"CAPE_API_TOKEN", "CAPE_DB_PASSWORD", "GUEST_CONTROL_TOKEN"}

# The policy: what each program is allowed to read. Anything not listed keeps no secret.
KEPT_BY_PROGRAM = {
    "api-token": {"CAPE_API_TOKEN", "CAPE_DB_PASSWORD"},
    "cape": {"CAPE_DB_PASSWORD"},
    "cape-processor": {"CAPE_DB_PASSWORD"},
    "cape-web": {"CAPE_DB_PASSWORD"},
    "guest-control": {"CAPE_API_TOKEN", "GUEST_CONTROL_TOKEN"},
}


def run_wrapper(*arguments: str, **environment: str) -> subprocess.CompletedProcess[str]:
    env = {"PATH": os.environ["PATH"], "KEEP": "visible", **environment}
    return subprocess.run(  # noqa: S603 - this repository's own script
        [str(WRAPPER), *arguments], env=env, capture_output=True, text=True, check=False
    )


def environment_of(result: subprocess.CompletedProcess[str]) -> set[str]:
    return {line.split("=", 1)[0] for line in result.stdout.splitlines()}


ALL_SECRETS = dict.fromkeys(SECRETS, "s3cret")


def test_a_program_keeps_none_of_the_secrets_unless_it_names_them():
    result = run_wrapper("--", "env", **ALL_SECRETS)

    assert result.returncode == 0
    assert environment_of(result).isdisjoint(SECRETS)


def test_it_keeps_exactly_the_named_secrets_and_leaves_other_variables_alone():
    result = run_wrapper("CAPE_DB_PASSWORD", "--", "env", **ALL_SECRETS)

    assert environment_of(result) & SECRETS == {"CAPE_DB_PASSWORD"}
    assert "KEEP=visible" in result.stdout


def test_the_command_gets_its_arguments_unchanged():
    result = run_wrapper("--", "printf", "%s|%s", "a b", "c", **ALL_SECRETS)

    assert result.stdout == "a b|c"


@pytest.mark.parametrize(
    "arguments", [["CAPE_DB_PASSWORD", "env"], ["NOT_A_SECRET", "--", "env"], []]
)
def test_a_misspelt_or_missing_part_refuses_to_start_the_program(arguments):
    result = run_wrapper(*arguments)

    assert result.returncode == 2
    assert result.stdout == ""


def programs() -> dict[str, configparser.SectionProxy]:
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(CAPE / "supervisord.conf")
    return {
        section.removeprefix("program:"): parser[section]
        for section in parser.sections()
        if section.startswith("program:")
    }


def launcher_and_kept(command: str) -> tuple[str, set[str]]:
    words = command.split()
    launcher = words[0]
    kept = set(words[1 : words.index("--")]) if "--" in words else set()
    return launcher, kept


@pytest.mark.parametrize("name", sorted(programs()))
def test_every_program_starts_through_the_wrapper_with_only_its_own_secrets(name):
    launcher, kept = launcher_and_kept(programs()[name]["command"])

    assert launcher == "/usr/local/lib/tartarus/keep-secrets"
    assert kept == KEPT_BY_PROGRAM.get(name, set())


def test_no_program_is_listed_in_the_policy_that_supervisord_does_not_start():
    assert set(KEPT_BY_PROGRAM) <= set(programs())


def test_no_environment_line_hands_a_program_a_secret_back():
    for program in programs().values():
        assert not [name for name in SECRETS if name in program.get("environment", "")]


def test_the_wrapper_knows_every_secret_the_compose_file_gives_the_container():
    compose = (CAPE.parent / "docker-compose.yml").read_text()
    cape_service = compose[compose.index("  cape:\n") : compose.index("\nnetworks:")]
    given = set(
        re.findall(r"^\s+([A-Z_]*(?:TOKEN|PASSWORD|SECRET|KEY)[A-Z_]*):", cape_service, re.M)
    )
    known = set(re.search(r"SECRETS=\(([^)]*)\)", WRAPPER.read_text()).group(1).split())

    assert given == known == SECRETS
