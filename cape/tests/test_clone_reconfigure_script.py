"""Static checks of the clone's identity script (guest/profiles/windows/reconfigure.ps1).

PowerShell cannot run here, so these pin the contract the host step relies on and the properties
the design decisions ask for; the script itself was not run on a guest when they were written.
"""

import re

import pytest
from test_windows_profile import param_block, script_text

SCRIPT = "reconfigure.ps1"
ADAPTER_LOOKUP = (
    "Get-NetAdapter -Physical | Where-Object Status -ne 'Disabled' | Select-Object -First 1"
)


@pytest.fixture(scope="module")
def text() -> str:
    return script_text(SCRIPT)


def phase_block(text: str, phase: str) -> str:
    """The body of `function <Verb>-Identity` that the `switch ($Phase)` runs for `phase`."""
    dispatch = re.search(rf"'{phase}'\s*\{{\s*([A-Za-z]+-[A-Za-z]+)", text)
    assert dispatch, f"the switch does not run anything for {phase}"
    function = re.search(rf"^function {dispatch.group(1)}\b.*?^\}}", text, re.DOTALL | re.MULTILINE)
    assert function, f"no function {dispatch.group(1)}"
    return function.group(0)


def step_block(text: str, title_fragment: str) -> str:
    """The body of the indented `Step '<title>' { ... }` whose title contains `title_fragment`."""
    start = re.search(
        r"^  Step [\"'][^\n]*" + re.escape(title_fragment) + r"[^\n]*\{$", text, re.MULTILINE
    )
    assert start, f"no step titled like {title_fragment!r}"
    end = re.search(r"^  \}$", text[start.end() :], re.MULTILINE)
    assert end
    return text[start.end() : start.end() + end.start()]


class TestTheParameters:
    def test_they_are_the_ones_the_host_step_passes(self, text):
        declared = re.findall(r"\[[a-z]+\]\s*\$([A-Za-z]+)", param_block(text))
        assert declared == [
            "Phase",
            "LogName",
            "MachineName",
            "GuestIp",
            "Gateway",
            "Prefix",
            "Decoys",
            "Token",
        ]

    def test_the_prefix_length_is_a_number(self, text):
        assert re.search(r"\[int\]\s*\$Prefix\b", param_block(text))

    def test_the_phase_is_one_of_three(self, text):
        assert "[ValidateSet('Report', 'Apply', 'Discard')]" in param_block(text)

    def test_decoys_is_text_because_the_driver_passes_every_value_quoted(self, text):
        assert re.search(r"\[string\]\s*\$Decoys\b", param_block(text))

    def test_the_script_ends_with_a_zero_exit_code_so_a_native_command_cannot_leak_its_own(
        self, text
    ):
        assert text.rstrip().endswith("exit 0")


class TestReport:
    def test_it_prints_the_four_facts_the_host_compares(self, text):
        block = phase_block(text, "Report")
        for key in ("hostname", "ip", "machine_guid", "boot_time"):
            assert re.search(rf"Result '{key}'", block), key

    def test_it_changes_nothing(self, text):
        block = phase_block(text, "Report")
        for verb in (
            "Rename-Computer",
            "Set-ItemProperty",
            "Remove-",
            "New-NetIPAddress",
            "wevtutil",
            "Restart-Computer",
            "Set-Content",
            "Add-Content",
        ):
            assert verb not in block, verb

    def test_the_address_leaves_out_the_link_local_one(self, text):
        assert "169.254" in text


class TestSettingTheAddress:
    def test_the_adapter_is_found_the_way_provisioning_finds_it(self, text):
        assert ADAPTER_LOOKUP in step_block(text, "static IP")
        assert ADAPTER_LOOKUP in script_text("provision.ps1")

    def test_an_address_that_is_already_set_is_left_alone(self, text):
        block = step_block(text, "static IP")
        check = block.index("PrefixOrigin")
        assert "'Manual'" in block[check:]
        assert "return" in block[check : block.index("New-NetIPAddress")]

    def test_it_follows_the_sequence_that_worked_on_the_real_guest(self, text):
        block = step_block(text, "static IP")
        order = [
            block.index(call)
            for call in (
                "Remove-NetIPAddress",
                "Remove-NetRoute",
                "New-NetIPAddress",
                "Set-DnsClientServerAddress",
            )
        ]
        assert order == sorted(order)
        assert "-DefaultGateway $Gateway" in block
        assert "-ServerAddresses $Gateway" in block


class TestAStepThatFailsIsLoggedAsFailed:
    """A cmdlet's error is not terminating by default, so the step would log "ok" over it."""

    @pytest.mark.parametrize(
        ("title", "cmdlet"),
        [
            ("static IP", "New-NetIPAddress"),
            ("static IP", "Set-DnsClientServerAddress"),
            ("computer name", "Rename-Computer"),
            ("MachineGuid", "Set-ItemProperty"),
        ],
    )
    def test_the_cmdlet_stops_on_error(self, text, title, cmdlet):
        line = next(line for line in step_block(text, title).splitlines() if cmdlet in line)
        assert "-ErrorAction Stop" in line


class TestRenaming:
    def test_the_computer_is_renamed_with_force_which_needs_the_reboot(self, text):
        block = step_block(text, "computer name")
        assert "Rename-Computer -NewName $MachineName -Force" in block

    def test_a_computer_that_already_has_the_name_is_left_alone(self, text):
        block = step_block(text, "computer name")
        assert block.index("$env:COMPUTERNAME -eq $MachineName") < block.index("Rename-Computer")


class TestMachineGuid:
    def test_a_fresh_guid_is_written_to_the_cryptography_key(self, text):
        block = step_block(text, "MachineGuid")
        assert "[guid]::NewGuid()" in block
        assert "MachineGuid" in block
        assert "Set-ItemProperty" in block
        assert "HKLM:\\SOFTWARE\\Microsoft\\Cryptography" in text

    def test_the_report_reads_the_same_key_the_step_writes(self, text):
        assert phase_block(text, "Report").count("$CryptographyKey") == 1
        assert "$CryptographyKey" in step_block(text, "MachineGuid")


class TestEventLogs:
    def test_every_log_is_listed_and_cleared_and_a_failing_one_is_ignored(self, text):
        block = step_block(text, "event logs")
        assert "wevtutil.exe el" in block
        assert re.search(r"wevtutil\.exe cl \$\w+ 2>\$null", block)


class TestDecoys:
    def test_they_are_applied_only_when_asked_for_and_by_the_decoys_script(self, text):
        block = step_block(text, "decoys")
        assert "$Decoys -ne 'true'" in block
        assert block.index("$Decoys -ne 'true'") < block.index("decoys.ps1")
        assert "Join-Path $PSScriptRoot 'decoys.ps1'" in block


class TestTheEndOfTheApplyPhase:
    def test_the_reboot_is_announced_with_the_hosts_token_and_comes_last(self, text):
        block = phase_block(text, "Apply")
        announce = block.index('Log "rebooting $Token"')
        reboot = block.index("Restart-Computer -Force")
        assert announce < reboot
        assert block.rstrip().rstrip("}").rstrip().endswith("Restart-Computer -Force")

    def test_the_steps_run_before_the_announcement(self, text):
        block = phase_block(text, "Apply")
        announcement = block.index("rebooting")
        for title in ("static IP", "computer name", "MachineGuid", "decoys", "event logs"):
            assert block.index(step_block(text, title)) < announcement, title

    def test_the_log_is_in_the_folder_the_script_was_uploaded_to(self, text):
        assert "Join-Path $PSScriptRoot $LogName" in text


class TestDiscard:
    def test_it_removes_the_log_and_nothing_else(self, text):
        block = phase_block(text, "Discard")
        assert "Remove-Item -Path $log " in block
        assert block.count("Remove-Item") == 1
