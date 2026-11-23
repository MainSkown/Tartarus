"""The `dns_static` lines of the fake hosts' names for INetSim (bin/lan_dns.py, bin/lan-dns-static).

INetSim answers every name with the gateway, so a fake host's name needs its own `dns_static` line.
One line INetSim refuses stops every one of its services (the S7 finding of the Step 0 spike): the
renderer therefore emits nothing it could refuse, and nothing at all when the presets cannot load.
"""

import importlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from test_control_http import BIN, load_script
from test_lan_presets import DEFAULT_SUBNET, SHIPPED_PRESETS, valid_preset

from guest_engine.lan_presets import Account, Host, Preset, Service, load_presets

lan_dns = importlib.import_module("lan_dns")
lan_dns_static = load_script("lan-dns-static")

CAPE = Path(__file__).resolve().parents[1]


def host(fqdn: str, address: str = "192.168.150.200") -> Host:
    return Host(
        fqdn=fqdn,
        host_offset=200,
        address=address,
        role="file-server",
        os_banner="",
        accounts=(Account("Administrator", "Password1"),),
        services=(Service("smb", 445),),
    )


def preset(*hosts: Host) -> Preset:
    return Preset(id="demo", name="Demo", description="", domain="demo.test", hosts=hosts)


@pytest.fixture
def messages() -> list[str]:
    return []


def write_presets(directory: Path, *documents: dict) -> Path:
    directory.mkdir()
    for document in documents:
        (directory / f"{document['id']}.json").write_text(json.dumps(document))
    return directory


def test_every_fake_host_becomes_one_dns_static_line_with_its_address(messages):
    presets = [
        preset(host("fs01.demo.test", "192.168.150.200"), host("dc01.demo.test", "192.168.150.201"))
    ]

    assert lan_dns.dns_static_lines(presets, messages.append) == [
        "dns_static fs01.demo.test 192.168.150.200",
        "dns_static dc01.demo.test 192.168.150.201",
    ]
    assert messages == []


def test_the_text_for_valid_presets_ends_in_a_newline_so_the_next_config_line_starts_clean(
    tmp_path, messages
):
    directory = write_presets(tmp_path / "presets", valid_preset("demo", 200))

    text = lan_dns.render(directory, DEFAULT_SUBNET, messages.append)

    assert text == (
        "dns_static demo-file.demo.test 192.168.150.200\n"
        "dns_static demo-print.demo.test 192.168.150.201\n"
    )


def test_the_shipped_presets_give_one_line_per_host_that_inetsim_accepts(messages):
    text = lan_dns.render(SHIPPED_PRESETS, DEFAULT_SUBNET, messages.append)

    hosts = [h for p in load_presets(SHIPPED_PRESETS, DEFAULT_SUBNET) for h in p.hosts]
    assert text.splitlines() == [f"dns_static {h.fqdn} {h.address}" for h in hosts]
    assert len(hosts) >= 10
    assert messages == []


def test_the_addresses_follow_the_guest_subnet(tmp_path, messages):
    directory = write_presets(tmp_path / "presets", valid_preset("demo", 200))

    text = lan_dns.render(directory, "10.77.3.0/24", messages.append)

    assert text.splitlines()[0] == "dns_static demo-file.demo.test 10.77.3.200"


@pytest.mark.parametrize(
    "unloadable",
    ["missing", "not-json", "bad-name"],
)
def test_presets_that_cannot_be_loaded_give_no_lines_and_say_why(tmp_path, messages, unloadable):
    directory = tmp_path / "presets"
    if unloadable == "not-json":
        directory.mkdir()
        (directory / "demo.json").write_text("{")
    if unloadable == "bad-name":
        broken = valid_preset("demo", 200)
        broken["hosts"][0]["fqdn"] = "fileserver"
        write_presets(directory, broken)

    text = lan_dns.render(directory, DEFAULT_SUBNET, messages.append)

    assert text == ""
    assert len(messages) == 1
    assert "no dns_static" in messages[0]
    assert str(directory) in messages[0]


def test_a_subnet_that_cannot_hold_the_fake_block_gives_no_lines_and_says_why(tmp_path, messages):
    directory = write_presets(tmp_path / "presets", valid_preset("demo", 200))

    text = lan_dns.render(directory, "192.168.150.0/25", messages.append)

    assert text == ""
    assert "no dns_static" in messages[0]


BAD_NAMES = [
    "fileserver",
    "FS01.demo.test",
    "fs_01.demo.test",
    "fs01.demo.test.",
    ".demo.test",
    "fs01..demo.test",
    "-fs01.demo.test",
    "fs01.demo.test\nservice_bind_address 0.0.0.0",
    "fs01.demo.test 10.0.0.1",
    "",
]


@pytest.mark.parametrize("name", BAD_NAMES)
def test_a_name_inetsim_would_refuse_is_never_emitted_even_if_it_got_past_the_loader(
    name, messages
):
    lines = lan_dns.dns_static_lines(
        [preset(host(name), host("ok.demo.test", "192.168.150.201"))], messages.append
    )

    assert lines == ["dns_static ok.demo.test 192.168.150.201"]
    assert len(messages) == 1
    assert "skipped" in messages[0]


@pytest.mark.parametrize("address", ["", "fs01", "192.168.150.256", "192.168.150.200\nx", "::1"])
def test_an_address_that_is_not_dotted_ipv4_is_never_emitted(address, messages):
    lines = lan_dns.dns_static_lines([preset(host("fs01.demo.test", address))], messages.append)

    assert lines == []
    assert len(messages) == 1


def test_the_command_prints_the_lines_for_the_presets_of_the_environment(tmp_path, capsys):
    directory = write_presets(tmp_path / "presets", valid_preset("demo", 200))
    environ = {"GUEST_LAN_PRESETS_DIR": str(directory), "GUEST_SUBNET": "192.168.150.0/24"}

    status = lan_dns_static.main(environ)

    assert status == 0
    assert capsys.readouterr().out.startswith("dns_static demo-file.demo.test 192.168.150.200\n")


def test_the_command_still_succeeds_and_prints_nothing_when_the_presets_are_unusable(
    tmp_path, capsys
):
    environ = {
        "GUEST_LAN_PRESETS_DIR": str(tmp_path / "absent"),
        "GUEST_SUBNET": "192.168.150.0/24",
    }

    status = lan_dns_static.main(environ)

    captured = capsys.readouterr()
    assert status == 0
    assert captured.out == ""
    assert captured.err.startswith("lan-dns-static:")


def test_the_script_runs_isolated_from_the_image_layout_with_guest_engine_beside_it(tmp_path):
    # In the image the scripts and guest_engine/ share one directory; `python3 -I` ignores
    # PYTHONPATH and the current directory, so the script must find guest_engine on its own.
    layout = tmp_path / "tartarus"
    layout.mkdir()
    shutil.copytree(
        CAPE / "guest_engine", layout / "guest_engine", ignore=shutil.ignore_patterns("__pycache__")
    )
    for name in ("lan-dns-static", "lan_dns.py"):
        shutil.copy(BIN / name, layout / name)
    directory = write_presets(tmp_path / "presets", valid_preset("demo", 200))
    environ = {
        "PATH": os.environ["PATH"],
        "GUEST_LAN_PRESETS_DIR": str(directory),
        "GUEST_SUBNET": "192.168.150.0/24",
    }

    run = subprocess.run(  # noqa: S603 - this repository's own script
        [sys.executable, "-I", str(layout / "lan-dns-static")],
        env=environ,
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
    )

    assert run.returncode == 0, run.stderr
    assert run.stdout.splitlines()[0] == "dns_static demo-file.demo.test 192.168.150.200"


ENTRYPOINT = (CAPE / "entrypoint.sh").read_text()


def test_the_entrypoint_appends_the_lines_to_the_inetsim_config_it_renders():
    function = ENTRYPOINT[ENTRYPOINT.index("render_inetsim_config() {") :].split("\n}\n")[0]

    assert "lan-dns-static" in function
    assert "/etc/inetsim/tartarus.conf" in function


def test_a_helper_that_fails_outright_still_lets_inetsim_start_without_the_lines():
    function = ENTRYPOINT[ENTRYPOINT.index("render_inetsim_config() {") :].split("\n}\n")[0]

    assert "|| fake_host_names=" in function
