"""The Windows guest profile under guest/profiles/windows/: its schema, names and scripts."""

import json
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from pathlib import Path
from string import Template
from xml.sax.saxutils import escape

import pytest

from guest_engine import giveaways
from guest_engine.profile import ProfileError, derive_badges, parse_profile

REPO = Path(__file__).parents[2]
PROFILE_DIR = REPO / "guest" / "profiles" / "windows"
MANIFEST = REPO / "guest" / "manifest.sha256"
SKIPPED_DIRECTORIES = {"__pycache__"}

HOSTILE = "a<b>&\"c'<!--]]></Value><Evil/>"
QUOTE_ENTITIES = {'"': "&quot;", "'": "&apos;"}
ALL_PLACEHOLDERS = {
    "UI_LANG",
    "INPUT_LOCALE",
    "IMAGE_INDEX",
    "GUEST_USERNAME",
    "GUEST_PASSWORD",
    "GUEST_HOSTNAME",
    "PRODUCT_KEY_BLOCK",
    "FIRST_LOGON_DESCRIPTION",
    "CD_MARKER_FILE",
    "WORK_DIR",
    "GUEST_IP",
    "DEFENDER",
    "DECOYS",
    "SYSMON",
    "FIREWALL_RULE_NAME",
    "TASK_NAME",
    "LOG_FILE",
    "DONE_MARKER",
}
NAME_KEYS = {
    "done_marker",
    "log_file",
    "firewall_rule",
    "scheduled_task",
    "cd_volume_label",
    "cd_marker_file",
    "first_logon_description",
}


def load_json(name: str) -> dict:
    return json.loads((PROFILE_DIR / name).read_text(encoding="utf-8"))


def profile_files() -> Iterator[Path]:
    for path in sorted(PROFILE_DIR.rglob("*")):
        relative_parts = path.relative_to(PROFILE_DIR).parts
        if path.is_file() and not SKIPPED_DIRECTORIES.intersection(relative_parts):
            yield path


def relative(path: Path) -> str:
    return path.relative_to(PROFILE_DIR).as_posix()


@pytest.fixture(scope="module")
def profile_data() -> dict:
    return load_json("profile.json")


@pytest.fixture(scope="module")
def profile(profile_data):
    return parse_profile(profile_data)


@pytest.fixture(scope="module")
def names() -> dict[str, str]:
    return load_json("names.json")


@pytest.fixture(scope="module")
def keyboards() -> dict[str, str]:
    return load_json("keyboards.json")


class TestProfileFile:
    def test_parses_and_round_trips(self, profile):
        assert parse_profile(profile.to_dict()) == profile

    def test_identifies_the_guest_family_and_cape_platform(self, profile):
        assert (profile.id, profile.family, profile.arch) == ("windows", "windows", "x64")
        assert profile.cape.platform == "windows"
        assert profile.cape.tags == ["windows", "win11"]

    def test_hardware_is_what_the_domain_template_defines(self, profile):
        domain = (REPO / "guest" / "domain.xml.tpl").read_text()
        hardware = profile.hardware
        assert (hardware.machine, hardware.boot) == ("q35", "uefi")
        assert (hardware.secure_boot, hardware.tpm) == (True, True)
        assert (hardware.disk_bus, hardware.nic_model, hardware.clock) == (
            "sata",
            "e1000e",
            "localtime",
        )
        assert "machine='q35'" in domain
        assert "secure='yes'" in domain
        assert "<tpm model='tpm-crb'>" in domain
        assert "bus='sata'" in domain
        assert "<model type='e1000e'/>" in domain
        assert "<clock offset='localtime'>" in domain

    def test_default_resources(self, profile):
        resources = profile.resources
        assert (resources.vcpus, resources.ram_mb, resources.disk_gb) == (2, 4096, 80)
        assert resources.min_disk_gb == 64
        assert resources.scratch_gb == 20

    def test_media_is_an_installer_read_by_the_inspector_that_exists(self, profile):
        assert profile.media.kinds == ["installer"]
        assert profile.media.inspector == "inspector"
        assert (PROFILE_DIR / "inspector.py").is_file()

    def test_option_keys_and_defaults(self, profile):
        assert [option.key for option in profile.options] == [
            "defender",
            "decoys",
            "sysmon",
            "key",
            "keyboard",
        ]
        assert profile.option_defaults() == {
            "defender": True,
            "decoys": False,
            "sysmon": True,
            "key": "",
            "keyboard": "Polish (Programmers)",
        }
        assert profile.clone_changeable_options() == {"defender", "decoys"}
        assert profile.option("key").type == "secret"

    def test_the_defender_help_explains_the_choice(self, profile):
        help_text = profile.option("defender").help.lower()
        assert "tamper protection" in help_text
        assert "samples" in help_text

    def test_keyboard_choices_are_layouts_of_the_keyboard_table(self, profile, keyboards):
        assert set(profile.option("keyboard").choices) <= set(keyboards)
        assert profile.option("keyboard").default in keyboards

    def test_identity_rules_refuse_what_windows_refuses(self, profile):
        account = profile.identity.account
        machine = profile.identity.machine
        assert {"Administrator", "Guest", "DefaultAccount", "SYSTEM", "WDAGUtilityAccount"} <= set(
            account.reserved
        )
        assert (account.generator, machine.generator) == ("first_name", "computer_name")
        assert profile.identity.password.generator == "password"
        assert profile.clone.computer_name_editable is True

    @pytest.mark.parametrize(
        ("candidate", "valid"),
        [
            ("DESKTOP-7A3K2P9", True),
            ("A", True),
            ("ABCDEFGHIJKLMNO", True),
            ("ABCDEFGHIJKLMNOP", False),
            ("12345", False),
            ("1A", True),
            ("-PC", False),
            ("PC-", False),
            ("PC_1", False),
            ("PC.1", False),
            ("", False),
        ],
    )
    def test_computer_name_pattern_is_the_netbios_rule(self, profile, candidate, valid):
        pattern = profile.identity.machine.pattern
        assert bool(re.fullmatch(pattern, candidate)) is valid

    @pytest.mark.parametrize(
        ("candidate", "valid"),
        [("Anna", True), ("a1_b-c", True), ("1anna", False), ("An na", False), ("A" * 21, False)],
    )
    def test_account_pattern(self, profile, candidate, valid):
        assert bool(re.fullmatch(profile.identity.account.pattern, candidate)) is valid

    def test_badges_follow_the_defender_option(self, profile):
        assert derive_badges(profile, {"defender": True}) == ["DEFENDER ON"]
        assert derive_badges(profile, {"defender": False}) == ["DEFENDER OFF"]

    def test_build_pipeline_with_defender_on(self, profile):
        steps = [entry.step for entry in profile.build_pipeline("installer", {"defender": True})]
        assert steps == [
            "preflight",
            "fetch",
            "define",
            "install",
            "provision",
            "snapshot",
            "register",
        ]

    def test_build_pipeline_with_defender_off_adds_tamper_off_after_provision(self, profile):
        steps = [entry.step for entry in profile.build_pipeline("installer", {"defender": False})]
        assert steps == [
            "preflight",
            "fetch",
            "define",
            "install",
            "provision",
            "tamper-off",
            "snapshot",
            "register",
        ]

    def test_clone_pipeline_turns_defender_on_or_off_after_reconfigure(self, profile):
        on = [entry.step for entry in profile.clone_pipeline({"defender": True})]
        off = [entry.step for entry in profile.clone_pipeline({"defender": False})]
        assert on == [
            "preflight",
            "copy",
            "define",
            "reconfigure",
            "defender-on",
            "snapshot",
            "register",
        ]
        assert off == [
            "preflight",
            "copy",
            "define",
            "reconfigure",
            "tamper-off",
            "snapshot",
            "register",
        ]

    def test_steps_that_use_the_desktop(self, profile):
        every_entry = [entry for _, entry in profile.pipeline_entries()]
        desktop = {entry.step for entry in every_entry if entry.desktop}
        assert desktop == {"install", "provision", "tamper-off", "reconfigure"}

    def test_install_keeps_todays_timeout(self, profile):
        install = next(e for e in profile.build_pipeline("installer", {}) if e.step == "install")
        assert install.timeout_s == 5400

    def test_agent_block(self, profile):
        agent = profile.agent
        assert (agent.port, agent.path_style) == (8000, "windows")
        assert agent.work_root == "C:\\ProgramData"
        assert agent.finish_dir == "C:\\Windows\\Temp"
        assert agent.shutdown == "acpi"
        assert agent.interactive.options == "interactive=1,nohuman=yes"
        assert agent.pre_snapshot is None

    def test_ready_marker_is_the_done_marker_of_the_names_table(self, profile, names):
        assert profile.agent.ready.marker == "{work_dir}\\" + names["done_marker"]

    def test_selftest_uses_the_moved_sample_and_facts_script(self, profile):
        assert profile.selftest.sample.source == "selftest/benign.c"
        assert profile.selftest.sample.build[0] == "x86_64-w64-mingw32-gcc"
        assert profile.selftest.facts.script == "selftest/guest-facts.ps1"
        assert (PROFILE_DIR / "selftest" / "benign.c").is_file()
        assert (PROFILE_DIR / "selftest" / "guest-facts.ps1").is_file()
        assert {signal.id for signal in profile.selftest.signals} == {
            "events.process",
            "events.file",
            "events.registry",
            "report.present",
            "report.dns_answer",
        }

    def test_packages_are_cape_package_names_and_not_auto(self, profile):
        assert set(profile.packages) == {
            "exe", "dll", "doc", "xls", "ppt", "ps1", "js", "vbs",
            "jar", "msi", "zip", "pdf", "python", "hta", "lnk",
        }  # fmt: skip
        assert "auto" not in profile.packages

    def test_timeouts(self, profile):
        assert (profile.timeouts.agent_s, profile.timeouts.idle_s, profile.timeouts.shutdown_s) == (
            900,
            60,
            300,
        )

    def test_a_broken_profile_is_still_rejected(self, profile_data):
        broken = dict(profile_data, arch="arm")
        with pytest.raises(ProfileError):
            parse_profile(broken)


class TestKeyboardTable:
    REQUIRED = (
        "Polish (Programmers)",
        "Polish (214)",
        "US",
        "UK",
        "German",
        "French",
        "Spanish",
        "Czech",
        "Italian",
        "Russian",
    )

    def test_has_the_required_layouts(self, keyboards):
        for layout in self.REQUIRED:
            assert any(key.startswith(layout) for key in keyboards), layout

    def test_values_are_input_locale_strings(self, keyboards):
        for layout, locale in keyboards.items():
            assert re.fullmatch(r"[0-9a-f]{4}:[0-9A-Fa-f]{8}", locale), (layout, locale)

    def test_the_default_input_locale_of_todays_build_is_in_the_table(self, keyboards):
        assert keyboards["Polish (Programmers)"] == "0415:00000415"

    def test_two_polish_layouts_differ(self, keyboards):
        assert keyboards["Polish (Programmers)"] != keyboards["Polish (214)"]


class TestNamesTable:
    def test_has_exactly_the_expected_names(self, names):
        assert set(names) == NAME_KEYS

    def test_no_name_is_a_giveaway(self, names):
        assert {
            key: giveaways.find_giveaway(value) for key, value in names.items()
        } == dict.fromkeys(names)

    def test_no_name_mentions_the_agent_or_the_tooling(self, names):
        for value in names.values():
            assert not re.search(r"agent|cape|sandbox|tartarus", value, re.IGNORECASE), value

    def test_the_cd_volume_label_is_a_valid_iso_label(self, names):
        assert re.fullmatch(r"[A-Z0-9_]{1,32}", names["cd_volume_label"])

    def test_file_names_are_plain_file_names(self, names):
        for key in ("done_marker", "log_file", "cd_marker_file"):
            assert re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", names[key]), key

    def test_names_appear_nowhere_else_in_the_profile(self, names):
        allowed_elsewhere = {
            ("profile.json", "done_marker"),
            # A sensible standalone default for a script also runnable outside the build pipeline.
            ("selftest/guest-facts.ps1", "scheduled_task"),
        }
        for path in profile_files():
            if relative(path) == "names.json":
                continue
            text = path.read_text(encoding="utf-8", errors="replace").lower()
            for key, value in names.items():
                if (relative(path), key) in allowed_elsewhere:
                    continue
                assert value.lower() not in text, f"{relative(path)} spells out {key}"


SCHEMA_KEY = re.compile(r'^\s*"cape": \{$')
# The sample is submitted for analysis, not provisioned; the Sigma rule, the end-to-end checks
# and the report fixtures all key on the strings it writes.
WHOLE_FILE_ALLOWED = {"selftest/benign.c"}
# Defender's own property name, reported as a FACT that verify-guest.sh prints.
LINE_ALLOWED = {
    "selftest/guest-facts.ps1": (
        "Fact 'defender.antivirus_enabled'",
        # The scanner's own vocabulary (decision 16's word list, duplicated here because
        # PowerShell cannot import guest_engine.giveaways): the words must appear as data.
        "$SubstringWords = @(",
        "$TokenWords = @(",
    ),
    # The EICAR test string's own text (Microsoft's standard string, not a project giveaway);
    # it is still split across two variables so no single literal spells the whole marker.
    # The adoption block records the guest M0b built before this scan existed, giveaways and all;
    # the card says so (decision 16), and it is the only place these two values are written.
    "profile.json": ('"password": "Tartarus1!"', '"work_dir": "C:\\\\tartarus"'),
    "tamper-off.ps1": ("$eicarSecondHalf = ",),
    "defender-on.ps1": ("$eicarSecondHalf = ",),
}


def giveaway_findings(path: Path) -> list[str]:
    name = relative(path)
    if name in WHOLE_FILE_ALLOWED:
        return []
    found = []
    for number, line in enumerate(
        path.read_text(encoding="utf-8", errors="replace").splitlines(), 1
    ):
        if any(allowed in line for allowed in LINE_ALLOWED.get(name, ())):
            continue
        lowered = line.lower()
        words = [word for word in giveaways.SUBSTRING_GIVEAWAYS if word in lowered]
        names_the_agent_file = "agent.py" in lowered
        is_schema_key = name == "profile.json" and SCHEMA_KEY.match(line)
        if "cape" in giveaways.tokens(line) and not (names_the_agent_file or is_schema_key):
            words.append("cape")
        found.extend(f"{name}:{number}: {word}" for word in words)
    return found


class TestNothingSaysWhatTheMachineIs:
    """Decision 16 / S0e: scan every shipped file for the words that give the guest away."""

    def test_the_scan_sees_the_files_of_the_profile(self):
        names = {relative(path) for path in profile_files()}
        assert {
            "provision.ps1",
            "autounattend.xml.tpl",
            "selftest/guest-facts.ps1",
            "inspector.py",
        } <= names

    def test_no_shipped_file_contains_a_giveaway(self):
        found = [finding for path in profile_files() for finding in giveaway_findings(path)]
        assert found == []

    def test_the_scan_catches_each_word(self, tmp_path, monkeypatch):
        monkeypatch.setattr(f"{__name__}.PROFILE_DIR", tmp_path)
        for index, word in enumerate(
            ("Tartarus", "sandbox", "MALWARE", "virus", "Cuckoo", "CAPE Agent")
        ):
            sample = tmp_path / f"sample{index}.ps1"
            sample.write_text(f"Write-Host 'a {word} here'\n")
            assert len(giveaway_findings(sample)) == 1, word

    def test_the_scan_does_not_flag_words_that_merely_contain_cape(self, tmp_path, monkeypatch):
        monkeypatch.setattr(f"{__name__}.PROFILE_DIR", tmp_path)
        sample = tmp_path / "sample.ps1"
        sample.write_text("# landscape escape ScapeGoat\nCopy agent.py to the folder\n")
        assert giveaway_findings(sample) == []

    def test_the_eicar_string_is_never_whole_in_a_file(self):
        for path in profile_files():
            text = path.read_text(encoding="utf-8", errors="replace")
            assert "ANTIVIRUS-TEST-FILE" not in text.upper(), relative(path)
            assert "EICAR-STANDARD-ANTIVIRUS" not in text.upper(), relative(path)


def escaped_values(values: dict[str, str]) -> dict[str, str]:
    return {key: escape(value, QUOTE_ENTITIES) for key, value in values.items()}


def product_key_block(key: str) -> str:
    if not key:
        return ""
    return (
        f"<ProductKey><Key>{escape(key, QUOTE_ENTITIES)}</Key>"
        "<WillShowUI>OnError</WillShowUI></ProductKey>"
    )


def render_autounattend(names: dict[str, str], keyboards: dict[str, str], **overrides: str) -> str:
    values = {
        "UI_LANG": "pl-PL",
        "INPUT_LOCALE": keyboards["Polish (Programmers)"],
        "IMAGE_INDEX": "5",
        "GUEST_USERNAME": "Anna",
        "GUEST_PASSWORD": "S3cret-pass",
        "GUEST_HOSTNAME": "DESKTOP-ABC1234",
        "FIRST_LOGON_DESCRIPTION": names["first_logon_description"],
        "CD_MARKER_FILE": names["cd_marker_file"],
        "WORK_DIR": "C:\\ProgramData\\qwertyui",
        "GUEST_IP": "192.168.150.100",
        "DEFENDER": "$true",
        "DECOYS": "$false",
        "SYSMON": "$true",
        "FIREWALL_RULE_NAME": names["firewall_rule"],
        "TASK_NAME": names["scheduled_task"],
        "LOG_FILE": names["log_file"],
        "DONE_MARKER": names["done_marker"],
    }
    key = overrides.pop("PRODUCT_KEY", "")
    values.update(overrides)
    rendered_values = escaped_values(values) | {"PRODUCT_KEY_BLOCK": product_key_block(key)}
    template = (PROFILE_DIR / "autounattend.xml.tpl").read_text(encoding="utf-8")
    return Template(template).safe_substitute(rendered_values)


UNATTEND = "{urn:schemas-microsoft-com:unattend}"


def parse(document: str) -> ET.Element:
    return ET.fromstring(document.encode("utf-8"))  # noqa: S314 - our own rendered output, not untrusted


def element_texts(root: ET.Element, tag: str) -> list[str]:
    return [element.text or "" for element in root.iter(UNATTEND + tag)]


def element_count(root: ET.Element) -> int:
    return sum(1 for _ in root.iter())


class TestAutounattendTemplate:
    def test_every_placeholder_the_renderer_must_fill_is_in_the_template(self):
        template = (PROFILE_DIR / "autounattend.xml.tpl").read_text(encoding="utf-8")
        used = set(re.findall(r"\$\{([A-Z_]+)\}", template))
        assert used == ALL_PLACEHOLDERS

    def test_renders_to_well_formed_xml_with_nothing_left_unfilled(self, names, keyboards):
        document = render_autounattend(names, keyboards)
        parse(document)
        assert "${" not in document

    def test_the_product_key_element_is_absent_without_a_key(self, names, keyboards):
        root = parse(render_autounattend(names, keyboards))
        assert list(root.iter(UNATTEND + "ProductKey")) == []
        assert element_texts(root, "Key") == ["/IMAGE/INDEX"]

    def test_a_blank_product_key_is_never_rendered_as_an_empty_element(self, names, keyboards):
        document = render_autounattend(names, keyboards)
        assert "<Key />" not in document
        assert "<Key/>" not in document
        assert "<Key></Key>" not in document

    def test_the_product_key_is_in_a_product_key_element_when_given(self, names, keyboards):
        root = parse(
            render_autounattend(names, keyboards, PRODUCT_KEY="AAAAA-BBBBB-CCCCC-DDDDD-EEEEE")
        )
        keys = [e.text for e in root.iter(UNATTEND + "ProductKey")]
        assert len(keys) == 1
        assert element_texts(root, "Key").count("AAAAA-BBBBB-CCCCC-DDDDD-EEEEE") == 1

    def test_the_edition_is_chosen_by_image_index(self, names, keyboards):
        root = parse(render_autounattend(names, keyboards, IMAGE_INDEX="7"))
        assert "7" in element_texts(root, "Value")

    def test_language_and_keyboard_come_from_the_media_and_the_table(self, names, keyboards):
        root = parse(
            render_autounattend(names, keyboards, UI_LANG="de-DE", INPUT_LOCALE=keyboards["German"])
        )
        assert set(element_texts(root, "UILanguage")) == {"de-DE"}
        assert set(element_texts(root, "InputLocale")) == {keyboards["German"]}

    def test_account_name_password_and_computer_name_are_placed_in_text(self, names, keyboards):
        root = parse(render_autounattend(names, keyboards))
        assert element_texts(root, "ComputerName") == ["DESKTOP-ABC1234"]
        assert element_texts(root, "Name") == ["Anna"]
        assert element_texts(root, "Username") == ["Anna"]
        assert [text.strip() for text in element_texts(root, "Password")] == ["", ""]
        assert element_texts(root, "Value").count("S3cret-pass") == 2

    @pytest.mark.parametrize(
        "field", ["GUEST_PASSWORD", "GUEST_USERNAME", "GUEST_HOSTNAME", "PRODUCT_KEY"]
    )
    def test_hostile_text_is_data_and_never_markup(self, names, keyboards, field):
        benign = {"PRODUCT_KEY": "X"} if field == "PRODUCT_KEY" else {}
        baseline = element_count(parse(render_autounattend(names, keyboards, **benign)))
        root = parse(render_autounattend(names, keyboards, **{field: HOSTILE}))
        assert element_count(root) == baseline
        all_text = "".join(element.text or "" for element in root.iter())
        assert HOSTILE in all_text
        assert list(root.iter("Evil")) == []

    def test_hostile_password_comes_back_exactly(self, names, keyboards):
        root = parse(render_autounattend(names, keyboards, GUEST_PASSWORD=HOSTILE))
        assert element_texts(root, "Value").count(HOSTILE) == 2

    def test_the_first_logon_command_names_come_from_the_table(self, names, keyboards):
        root = parse(render_autounattend(names, keyboards))
        description = element_texts(root, "Description")
        command = element_texts(root, "CommandLine")
        assert description == [names["first_logon_description"]]
        assert len(command) == 1
        assert names["cd_marker_file"] in command[0]
        for argument in (
            "-WorkDir",
            "-GuestIp",
            "-Defender",
            "-Decoys",
            "-Sysmon",
            "-FirewallRuleName",
            "-TaskName",
            "-LogName",
            "-DoneMarker",
        ):
            assert argument in command[0], argument

    def test_the_template_spells_out_none_of_the_names(self, names):
        template = (PROFILE_DIR / "autounattend.xml.tpl").read_text(encoding="utf-8").lower()
        assert [value for value in names.values() if value.lower() in template] == []

    def test_no_leftover_literals_of_the_old_build(self):
        template = (PROFILE_DIR / "autounattend.xml.tpl").read_text(encoding="utf-8")
        for literal in ("Analyst", "DESKTOP-7A3K2P9", "Tartarus1!"):
            assert literal not in template


def script_text(name: str) -> str:
    return (PROFILE_DIR / name).read_text(encoding="utf-8")


def param_block(text: str) -> str:
    match = re.search(r"^param\((.*?)^\)", text, re.DOTALL | re.MULTILINE)
    assert match, "no param block"
    return match.group(1)


def step_block(text: str, title_fragment: str) -> str:
    """The body of the `Step '<title>' { ... }` whose title contains `title_fragment`."""
    start = re.search(
        r"^Step '[^']*" + re.escape(title_fragment) + r"[^']*' \{", text, re.MULTILINE
    )
    assert start, f"no step titled like {title_fragment!r}"
    following = re.search(r"^\}", text[start.end() :], re.MULTILINE)
    assert following
    return text[start.end() : start.end() + following.start()]


class TestProvisionScript:
    DEFENDER_GUARD = re.compile(r"if \(\$Defender\) \{[^}]*\breturn\b")
    PARAMETERS = (
        "Media",
        "WorkDir",
        "GuestIp",
        "Gateway",
        "Prefix",
        "Defender",
        "Decoys",
        "Sysmon",
        "FirewallRuleName",
        "TaskName",
        "LogName",
        "DoneMarker",
    )

    def test_has_the_parameters(self):
        block = param_block(script_text("provision.ps1"))
        declared = tuple(re.findall(r"\[[^\[\]]+\]\s*\$([A-Za-z]+)", block))
        assert declared == self.PARAMETERS

    def test_the_switches_are_booleans(self):
        block = param_block(script_text("provision.ps1"))
        for name in ("Defender", "Decoys", "Sysmon"):
            assert re.search(rf"\[bool\]\s*\${name}\b", block), name

    def test_defender_policy_keys_are_written_only_when_defender_is_off(self):
        text = script_text("provision.ps1")
        assert "DisableRealtimeMonitoring" not in text
        assert "Policies\\Microsoft\\Windows Defender" not in text
        block = step_block(text, "Defender")
        guard = self.DEFENDER_GUARD.search(block)
        assert guard, "the policy keys must sit behind an early return when Defender stays on"
        assert guard.start() < block.index("defender-settings.ps1")
        assert "-Mode Off" in block

    def test_the_guard_test_fails_when_the_guard_is_gone(self):
        text = script_text("provision.ps1").replace("if ($Defender) {", "if ($false) {")
        assert self.DEFENDER_GUARD.search(step_block(text, "Defender")) is None

    def test_decoys_and_sysmon_run_only_when_asked(self):
        text = script_text("provision.ps1")
        assert re.search(r"if \(-not \$Decoys\) \{[^}]*\breturn\b", step_block(text, "decoys"))
        assert re.search(r"if \(-not \$Sysmon\) \{[^}]*\breturn\b", step_block(text, "Sysmon"))

    def test_sysmon_is_installed_with_the_config_and_verified(self):
        block = step_block(script_text("provision.ps1"), "Sysmon")
        assert "-accepteula" in block
        assert "-i" in block
        assert "sysmon-config.xml" in block
        assert "Get-Service" in block
        assert "Microsoft-Windows-Sysmon/Operational" in block

    def test_names_and_folder_come_from_parameters(self):
        text = script_text("provision.ps1")
        assert "-DisplayName $FirewallRuleName" in text
        assert "-TaskName $TaskName" in text
        assert "$WorkDir" in text
        assert "C:\\tartarus" not in text

    def test_the_done_marker_is_written_last(self):
        lines = [line for line in script_text("provision.ps1").splitlines() if line.strip()]
        assert "$DoneMarker" in lines[-1]

    def test_the_log_is_left_for_the_cleanup_script(self):
        text = script_text("provision.ps1")
        assert "Remove-Item" not in text
        assert "$LogName" in text

    def test_keeps_the_proven_m0b_settings(self):
        text = script_text("provision.ps1")
        for kept in (
            "python-3.11.9.exe",
            "InstallAllUsers=1",
            "TargetDir=C:\\Python311",
            "pillow-",
            "Get-NetAdapter -Physical",
            "EnableLUA",
            "NoAutoUpdate",
            "EnableSmartScreen",
            "Set-NetFirewallProfile",
            "-RunLevel Highest",
        ):
            assert kept in text, kept


class TestCleanupScript:
    def test_removes_everything_but_the_agent_and_the_done_marker(self):
        text = script_text("cleanup.ps1")
        block = param_block(text)
        assert "$WorkDir" in block
        assert "$DoneMarker" in block
        assert "agent.py" in text
        assert "Remove-Item" in text


class TestDecoysScript:
    def test_creates_traces_with_spread_out_dates_and_no_network(self):
        text = script_text("decoys.ps1")
        assert "CreationTime" in text
        assert "LastWriteTime" in text
        assert ".lnk" in text
        for module in (
            "Invoke-WebRequest",
            "Invoke-RestMethod",
            "Net.WebClient",
            "Start-BitsTransfer",
        ):
            assert module not in text

    def test_is_idempotent_and_logged(self):
        text = script_text("decoys.ps1")
        assert "Test-Path" in text
        assert "Write-Output" in text or "Write-Host" in text


class TestDefenderSettingsScript:
    def test_sets_every_policy_key_of_decision_11_when_off(self):
        text = script_text("defender-settings.ps1")
        for value in (
            "DisableRealtimeMonitoring",
            "DisableBehaviorMonitoring",
            "DisableOnAccessProtection",
            "DisableIOAVProtection",
            "DisableScriptScanning",
            "SpynetReporting",
            "SubmitSamplesConsent",
        ):
            assert value in text, value

    def test_reporting_keys_get_the_values_that_mean_disabled(self):
        text = script_text("defender-settings.ps1")
        assert re.search(r"Name = 'SpynetReporting';\s*Value = 0", text)
        assert re.search(r"Name = 'SubmitSamplesConsent';\s*Value = 2", text)

    def test_has_an_off_and_an_on_mode_that_removes_the_keys(self):
        text = script_text("defender-settings.ps1")
        assert "ValidateSet('Off', 'On')" in param_block(text)
        assert "Remove-ItemProperty" in text
        assert "-Force" in text


class TestSecurityWindowLookup:
    def test_tamper_off_finds_the_app_frame_by_title_not_a_core_window(self):
        text = script_text("tamper-off.ps1")
        assert "CoreWindow" not in text
        assert "ApplicationFrameWindow" in text
        assert "Zabezpieczenia Windows" in text
        assert "Windows Security" in text


class TestDefenderScripts:
    def test_tamper_off_follows_decision_11_in_order(self):
        text = script_text("tamper-off.ps1")
        order = [
            "defender-settings.ps1",
            "windowsdefender://threatsettings",
            "$KnownNames",
            "settingToggle",
            "TogglePattern",
            "IsTamperProtected",
            "RealTimeProtectionEnabled",
            "Set-MpPreference",
            "Start-MpScan",
        ]
        positions = [text.index(marker) for marker in order]
        assert positions == sorted(positions)

    def test_tamper_off_knows_the_localized_names(self):
        text = script_text("tamper-off.ps1")
        for name in (
            "Ochrona przed naruszeniami",
            "Ochrona przed manipulacją",
            "Tamper Protection",
        ):
            assert name in text

    def test_exit_codes(self):
        text = script_text("tamper-off.ps1")
        for code in ("0", "10", "20", "30"):
            assert re.search(rf"\bexit {code}\b", text), code

    @pytest.mark.parametrize("script", ["tamper-off.ps1", "defender-on.ps1"])
    def test_the_eicar_string_is_assembled_from_two_halves(self, script):
        text = script_text(script)
        assert "EICAR" in text
        assert "$eicarFirstHalf + $eicarSecondHalf" in text
        assert "EICAR-STANDARD-ANTIVIRUS" not in text.upper()

    @pytest.mark.parametrize("script", ["tamper-off.ps1", "defender-on.ps1"])
    def test_loads_ui_automation_and_writes_result_lines(self, script):
        text = script_text(script)
        assert "Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes" in text
        assert "RESULT " in text

    def test_defender_on_is_idempotent_and_proves_removal(self):
        text = script_text("defender-on.ps1")
        assert text.index("IsTamperProtected") < text.index("defender-settings.ps1")
        assert "-Mode On" in text
        assert "RealTimeProtectionEnabled" in text
        assert len(re.findall(r"\bexit 0\b", text)) >= 2


class TestSysmon:
    def test_config_is_well_formed_and_small(self):
        path = PROFILE_DIR / "sysmon-config.xml"
        root = ET.parse(path).getroot()  # noqa: S314 - a file this repo ships, not untrusted input
        assert root.tag == "Sysmon"
        assert root.get("schemaversion")
        assert len(path.read_text().splitlines()) < 150
        events = {child.tag for child in root.find("EventFiltering")}
        assert {"ProcessCreate", "NetworkConnect", "FileCreate", "RegistryEvent"} <= events
        assert "ImageLoad" not in events or root.find("EventFiltering/ImageLoad") is None

    def test_the_binary_is_pinned_in_the_manifest(self):
        entries = [
            line.split()
            for line in MANIFEST.read_text().splitlines()
            if line.strip() and not line.startswith("#")
        ]
        sysmon = [entry for entry in entries if entry[1] == "Sysmon64.exe"]
        assert len(sysmon) == 1
        digest, _, url = sysmon[0]
        assert re.fullmatch(r"[0-9a-f]{64}", digest)
        assert url.startswith("https://")
        assert "sysinternals.com" in url


class TestFactsScript:
    def test_keeps_the_fact_lines_verify_guest_relies_on(self):
        text = script_text("selftest/guest-facts.ps1")
        for key in (
            "system.manufacturer",
            "bios.serial",
            "nic.mac",
            "os.hostname",
            "defender.tamper_protected",
        ):
            assert f"Fact '{key}'" in text

    def test_scans_the_places_of_decision_16(self):
        text = script_text("selftest/guest-facts.ps1")
        for place in (
            "Get-LocalUser",
            "Get-ScheduledTask",
            "Get-Service",
            "Get-NetFirewallRule",
            "CurrentVersion\\Run",
            "C:\\ProgramData",
            "C:\\Users",
            "Uninstall",
        ):
            assert place in text, place
        assert "GIVEAWAY " in text

    def test_the_word_list_is_a_parameter_not_a_literal(self):
        text = script_text("selftest/guest-facts.ps1")
        block = param_block(text)
        for name in ("SubstringWords", "TokenWords", "PrefixWords"):
            assert f"${name}" in block, name


def powershell_files() -> list[Path]:
    return [path for path in profile_files() if path.suffix == ".ps1"]


class TestPowerShellSyntax:
    @pytest.mark.skipif(
        shutil.which("pwsh") is None,
        reason="pwsh is not installed here; the parser check needs PowerShell (run it in "
        "mcr.microsoft.com/powershell or on the live guest)",
    )
    def test_every_script_parses(self):
        parse_call = "[System.Management.Automation.Language.Parser]::ParseFile"
        report = "Write-Output ('{0}:{1}: {2}' -f $file, $e.Extent.StartLineNumber, $e.Message)"
        script = (
            "$failed = $false; foreach ($file in $args) { $errors = $null; "
            f"{parse_call}($file, [ref]$null, [ref]$errors) | Out-Null; "
            f"foreach ($e in $errors) {{ {report}; $failed = $true }} }}; "
            "if ($failed) { exit 1 }"
        )
        result = subprocess.run(  # noqa: S603 - fixed argv, files from the repo
            ["pwsh", "-NoProfile", "-Command", script, *map(str, powershell_files())],  # noqa: S607
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    def test_there_are_scripts_to_parse(self):
        assert {path.name for path in powershell_files()} >= {
            "provision.ps1",
            "cleanup.ps1",
            "decoys.ps1",
            "defender-settings.ps1",
            "tamper-off.ps1",
            "defender-on.ps1",
            "guest-facts.ps1",
        }
