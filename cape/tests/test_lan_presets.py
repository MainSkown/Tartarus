import copy
import json
from pathlib import Path
from typing import Any

import pytest

from guest_engine.config import EngineConfig
from guest_engine.lan_presets import PresetError, dns_records, load_presets

SHIPPED_PRESETS = Path(__file__).resolve().parents[2] / "guest" / "lan-presets"
DEFAULT_SUBNET = "192.168.150.0/24"

SHIPPED_OFFSET_RANGES = {
    "small-office": range(200, 216),
    "flat-home": range(216, 232),
    "domain-servers": range(232, 248),
}


def valid_preset(preset_id: str = "demo", first_offset: int = 200) -> dict[str, Any]:
    return {
        "id": preset_id,
        "name": "Demo",
        "description": "A demo network",
        "domain": "demo.test",
        "hosts": [
            {
                "fqdn": f"{preset_id}-file.demo.test",
                "host_offset": first_offset,
                "role": "file-server",
                "os_banner": "Windows Server 2019 Standard 10.0.17763",
                "accounts": [{"user": "Administrator", "password": "Password1"}],
                "services": [
                    {"kind": "smb", "port": 445, "options": {"shares": ["Public"]}},
                    {"kind": "rdp", "port": 3389, "options": {}},
                ],
            },
            {
                "fqdn": f"{preset_id}-print.demo.test",
                "host_offset": first_offset + 1,
                "role": "printer",
                "os_banner": "Embedded Linux",
                "accounts": [],
                "services": [
                    {"kind": "ssh", "port": 22, "options": {"banner": "OpenSSH_8.9p1 Ubuntu"}}
                ],
            },
        ],
    }


def write_presets(directory: Path, *presets: dict[str, Any]) -> Path:
    directory.mkdir(exist_ok=True)
    for preset in presets:
        (directory / f"{preset['id']}.json").write_text(json.dumps(preset))
    return directory


def load_error(tmp_path: Path, *presets: dict[str, Any], subnet: str = DEFAULT_SUBNET) -> str:
    directory = write_presets(tmp_path / "presets", *presets)
    with pytest.raises(PresetError) as caught:
        load_presets(directory, subnet)
    return str(caught.value)


def mutated(change) -> dict[str, Any]:
    preset = copy.deepcopy(valid_preset())
    change(preset)
    return preset


class TestShippedPresets:
    def test_the_three_presets_validate_together(self):
        presets = load_presets(SHIPPED_PRESETS, DEFAULT_SUBNET)

        assert {preset.id for preset in presets} == set(SHIPPED_OFFSET_RANGES)

    def test_each_preset_keeps_to_its_own_block_of_sixteen_addresses(self):
        for preset in load_presets(SHIPPED_PRESETS, DEFAULT_SUBNET):
            for host in preset.hosts:
                assert host.host_offset in SHIPPED_OFFSET_RANGES[preset.id], host.fqdn

    def test_every_fqdn_ends_in_its_presets_domain(self):
        for preset in load_presets(SHIPPED_PRESETS, DEFAULT_SUBNET):
            assert all(host.fqdn.endswith(f".{preset.domain}") for host in preset.hosts)

    def test_the_small_office_has_the_hosts_the_spec_names(self):
        office = next(
            p for p in load_presets(SHIPPED_PRESETS, DEFAULT_SUBNET) if p.id == "small-office"
        )

        services = {host.fqdn: {service.kind for service in host.services} for host in office.hosts}

        assert services["dc01.corp.local"] == {"smb", "ldap", "rdp", "winrm"}
        assert services["printer01.corp.local"] == {"ssh"}
        assert {host.host_offset for host in office.hosts} == set(range(200, 206))

    def test_every_smb_host_has_an_account_and_every_host_a_banner(self):
        for preset in load_presets(SHIPPED_PRESETS, DEFAULT_SUBNET):
            for host in preset.hosts:
                assert host.os_banner
                if any(service.kind == "smb" for service in host.services):
                    assert host.accounts, host.fqdn

    def test_the_subnet_decides_the_addresses(self):
        default = load_presets(SHIPPED_PRESETS, DEFAULT_SUBNET)
        moved = load_presets(SHIPPED_PRESETS, "10.77.4.0/24")

        dc01 = next(h for p in moved for h in p.hosts if h.fqdn == "dc01.corp.local")
        assert dc01.address == "10.77.4.200"
        assert [h.address for p in default for h in p.hosts] != [
            h.address for p in moved for h in p.hosts
        ]


class TestResolution:
    def test_a_host_offset_becomes_an_address_in_the_given_subnet(self, tmp_path):
        directory = write_presets(tmp_path / "presets", valid_preset())

        (preset,) = load_presets(directory, "10.77.4.0/24")

        assert [host.address for host in preset.hosts] == ["10.77.4.200", "10.77.4.201"]

    def test_the_services_and_accounts_are_read_as_written(self, tmp_path):
        directory = write_presets(tmp_path / "presets", valid_preset())

        (preset,) = load_presets(directory, DEFAULT_SUBNET)
        file_server = preset.hosts[0]

        assert [(s.kind, s.port) for s in file_server.services] == [("smb", 445), ("rdp", 3389)]
        assert file_server.services[0].options == {"shares": ["Public"]}
        assert (file_server.accounts[0].user, file_server.accounts[0].password) == (
            "Administrator",
            "Password1",
        )

    def test_presets_come_back_in_file_name_order(self, tmp_path):
        directory = write_presets(
            tmp_path / "presets", valid_preset("zeta", 216), valid_preset("alpha", 200)
        )

        assert [p.id for p in load_presets(directory, DEFAULT_SUBNET)] == ["alpha", "zeta"]

    def test_an_empty_directory_has_no_presets(self, tmp_path):
        (tmp_path / "presets").mkdir()

        assert load_presets(tmp_path / "presets", DEFAULT_SUBNET) == []


class TestFiles:
    def test_a_missing_directory_is_an_error_naming_it(self, tmp_path):
        with pytest.raises(PresetError, match=r"no-such-dir.*is not a directory"):
            load_presets(tmp_path / "no-such-dir", DEFAULT_SUBNET)

    def test_malformed_json_is_an_error_naming_the_file(self, tmp_path):
        directory = tmp_path / "presets"
        directory.mkdir()
        (directory / "broken.json").write_text("{not json")

        with pytest.raises(PresetError, match=r"broken\.json.*not valid JSON"):
            load_presets(directory, DEFAULT_SUBNET)

    def test_a_json_file_that_is_not_an_object_is_refused(self, tmp_path):
        directory = tmp_path / "presets"
        directory.mkdir()
        (directory / "list.json").write_text("[]")

        with pytest.raises(PresetError, match=r"list\.json.*must be an object"):
            load_presets(directory, DEFAULT_SUBNET)

    def test_the_id_must_match_the_file_name(self, tmp_path):
        directory = tmp_path / "presets"
        directory.mkdir()
        (directory / "other.json").write_text(json.dumps(valid_preset("demo")))

        with pytest.raises(PresetError, match=r"other\.json.*id: 'demo' does not match"):
            load_presets(directory, DEFAULT_SUBNET)

    def test_files_that_are_not_json_are_ignored(self, tmp_path):
        directory = write_presets(tmp_path / "presets", valid_preset())
        (directory / "README.md").write_text("notes")

        assert len(load_presets(directory, DEFAULT_SUBNET)) == 1

    def test_a_subnet_that_is_not_a_slash_24_is_refused(self, tmp_path):
        directory = write_presets(tmp_path / "presets", valid_preset())

        with pytest.raises(ValueError, match="must be a /24"):
            load_presets(directory, "10.0.0.0/16")


class TestRules:
    @pytest.mark.parametrize("offset", [199, 248, 0, 250])
    def test_an_offset_outside_the_block_is_refused(self, tmp_path, offset):
        preset = mutated(lambda p: p["hosts"][0].update(host_offset=offset))

        message = load_error(tmp_path, preset)

        assert (
            f"hosts[0].host_offset: offset {offset} is outside the fake LAN block 200-247"
            in message
        )

    def test_two_presets_may_not_share_an_address(self, tmp_path):
        first = valid_preset("first", 200)
        second = valid_preset("second", 201)

        message = load_error(tmp_path, first, second)

        assert "second.json" in message
        assert (
            "hosts[0].host_offset: address 192.168.150.201 is also used by first.json hosts[1]"
            in message
        )

    def test_two_hosts_of_one_preset_may_not_share_an_address(self, tmp_path):
        preset = mutated(lambda p: p["hosts"][1].update(host_offset=200))

        message = load_error(tmp_path, preset)

        assert (
            "hosts[1].host_offset: address 192.168.150.200 is also used by demo.json hosts[0]"
            in message
        )

    def test_fqdns_are_unique_across_presets(self, tmp_path):
        first = valid_preset("first", 200)
        second = valid_preset("second", 216)
        second["hosts"][0]["fqdn"] = first["hosts"][0]["fqdn"]

        message = load_error(tmp_path, first, second)

        assert "second.json" in message
        assert (
            "hosts[0].fqdn: 'first-file.demo.test' is also used by first.json hosts[0]" in message
        )

    @pytest.mark.parametrize(
        ("fqdn", "reason"),
        [
            ("fileserver", "must have at least two labels"),
            ("FS01.demo.test", "must be lower case"),
            ("fs_01.demo.test", "must not contain an underscore"),
            ("fs 01.demo.test", "may hold only a-z, 0-9 and hyphens"),
            ("-fs01.demo.test", "may hold only a-z, 0-9 and hyphens"),
            ("fs01..demo.test", "may hold only a-z, 0-9 and hyphens"),
            ("fs01.demo.test.", "may hold only a-z, 0-9 and hyphens"),
            ("fs01.other.test", "must end in the preset's domain .demo.test"),
        ],
    )
    def test_an_fqdn_that_inetsim_would_refuse_is_refused(self, tmp_path, fqdn, reason):
        preset = mutated(lambda p: p["hosts"][0].update(fqdn=fqdn))

        message = load_error(tmp_path, preset)

        assert f"hosts[0].fqdn: {reason}" in message

    @pytest.mark.parametrize("port", [0, -1, 65536, 100000])
    def test_a_port_outside_1_to_65535_is_refused(self, tmp_path, port):
        preset = mutated(lambda p: p["hosts"][0]["services"][0].update(port=port))

        message = load_error(tmp_path, preset)

        assert "hosts[0].services[0].port: must be between 1 and 65535" in message

    def test_a_port_that_is_not_an_integer_is_refused(self, tmp_path):
        preset = mutated(lambda p: p["hosts"][0]["services"][0].update(port="445"))

        assert "services[0].port: must be an integer" in load_error(tmp_path, preset)

    def test_an_unknown_service_kind_is_refused(self, tmp_path):
        preset = mutated(lambda p: p["hosts"][0]["services"][0].update(kind="telnet"))

        message = load_error(tmp_path, preset)

        assert (
            "hosts[0].services[0].kind: must be one of smb, rdp, winrm, ssh, ldap, mssql" in message
        )

    def test_a_port_may_serve_only_one_service_on_a_host(self, tmp_path):
        preset = mutated(lambda p: p["hosts"][0]["services"][1].update(port=445))

        message = load_error(tmp_path, preset)

        assert "hosts[0].services[1].port: 445 is already served by services[0]" in message

    def test_an_smb_host_needs_an_account(self, tmp_path):
        preset = mutated(lambda p: p["hosts"][0].update(accounts=[]))

        message = load_error(tmp_path, preset)

        assert "hosts[0].accounts: a host that serves smb needs at least one account" in message

    def test_a_host_without_the_accounts_key_is_checked_the_same_way(self, tmp_path):
        preset = mutated(lambda p: p["hosts"][0].pop("accounts"))

        assert "hosts[0].accounts: a host that serves smb needs" in load_error(tmp_path, preset)

    def test_a_host_that_does_not_serve_smb_may_have_no_accounts(self, tmp_path):
        directory = write_presets(tmp_path / "presets", valid_preset())

        assert load_presets(directory, DEFAULT_SUBNET)[0].hosts[1].accounts == ()

    def test_an_account_needs_a_user_and_a_password(self, tmp_path):
        preset = mutated(
            lambda p: p["hosts"][0].update(accounts=[{"user": "root", "password": ""}])
        )

        assert "hosts[0].accounts[0].password: must be a non-empty string" in load_error(
            tmp_path, preset
        )

    def test_a_user_may_appear_once_per_host(self, tmp_path):
        account = {"user": "admin", "password": "admin"}
        preset = mutated(lambda p: p["hosts"][0].update(accounts=[account, account]))

        assert "hosts[0].accounts[1]: 'admin' is listed twice" in load_error(tmp_path, preset)

    def test_a_role_is_a_lower_case_slug(self, tmp_path):
        preset = mutated(lambda p: p["hosts"][0].update(role="File Server"))

        assert "hosts[0].role: must match" in load_error(tmp_path, preset)

    def test_a_preset_needs_hosts(self, tmp_path):
        preset = mutated(lambda p: p.update(hosts=[]))

        assert "hosts: must be a non-empty list" in load_error(tmp_path, preset)

    def test_a_host_needs_services(self, tmp_path):
        preset = mutated(lambda p: p["hosts"][0].update(services=[]))

        assert "hosts[0].services: must be a non-empty list" in load_error(tmp_path, preset)

    @pytest.mark.parametrize("missing", ["id", "name", "description", "domain", "hosts"])
    def test_every_preset_field_is_required(self, tmp_path, missing):
        preset = mutated(lambda p: p.pop(missing))
        directory = tmp_path / "presets"
        directory.mkdir()
        (directory / "demo.json").write_text(json.dumps(preset))

        with pytest.raises(PresetError, match=f"{missing}: is required"):
            load_presets(directory, DEFAULT_SUBNET)

    @pytest.mark.parametrize("missing", ["fqdn", "host_offset", "role", "os_banner", "services"])
    def test_every_host_field_is_required(self, tmp_path, missing):
        preset = mutated(lambda p: p["hosts"][1].pop(missing))

        assert f"hosts[1].{missing}: is required" in load_error(tmp_path, preset)


class TestUnknownKeys:
    @pytest.mark.parametrize(
        ("where", "path"),
        [
            (lambda p: p, "hostz"),
            (lambda p: p["hosts"][0], "hosts[0].os_bannr"),
            (lambda p: p["hosts"][0]["accounts"][0], "hosts[0].accounts[0].pasword"),
            (lambda p: p["hosts"][0]["services"][0], "hosts[0].services[0].portt"),
            (
                lambda p: p["hosts"][0]["services"][0]["options"],
                "hosts[0].services[0].options.share",
            ),
        ],
    )
    def test_a_typo_is_not_passed_over(self, tmp_path, where, path):
        preset = valid_preset()
        where(preset)[path.rsplit(".", 1)[-1].split("[")[0]] = "x"

        assert f"{path}: is not a known field" in load_error(tmp_path, preset)


class TestServiceOptions:
    def test_the_implied_smb_shares_are_not_listed(self, tmp_path):
        preset = mutated(
            lambda p: p["hosts"][0]["services"][0]["options"].update(shares=["Public", "c$"])
        )

        message = load_error(tmp_path, preset)

        assert "options.shares[1]: C$ is implied, do not list it" in message

    def test_smb_shares_must_be_a_list_of_names(self, tmp_path):
        preset = mutated(lambda p: p["hosts"][0]["services"][0]["options"].update(shares="Public"))

        assert "options.shares: must be a list" in load_error(tmp_path, preset)

    def test_only_smb_has_shares(self, tmp_path):
        preset = mutated(
            lambda p: p["hosts"][0]["services"][1]["options"].update(shares=["Public"])
        )

        assert "services[1].options.shares: is not a known field" in load_error(tmp_path, preset)

    def test_an_ssh_banner_is_one_line_of_printable_text(self, tmp_path):
        preset = mutated(
            lambda p: p["hosts"][1]["services"][0]["options"].update(banner="OpenSSH\nEvil")
        )

        assert "hosts[1].services[0].options.banner: must match" in load_error(tmp_path, preset)

    def test_options_may_be_left_out(self, tmp_path):
        preset = valid_preset()
        del preset["hosts"][0]["services"][1]["options"]
        directory = write_presets(tmp_path / "presets", preset)

        (loaded,) = load_presets(directory, DEFAULT_SUBNET)

        assert loaded.hosts[0].services[1].options == {}


class TestPublicView:
    def test_it_lists_the_hosts_with_addresses_and_service_ports(self, tmp_path):
        directory = write_presets(tmp_path / "presets", valid_preset())
        (preset,) = load_presets(directory, "10.77.4.0/24")

        assert preset.public() == {
            "id": "demo",
            "name": "Demo",
            "description": "A demo network",
            "hosts": [
                {
                    "fqdn": "demo-file.demo.test",
                    "address": "10.77.4.200",
                    "role": "file-server",
                    "services": [{"kind": "smb", "port": 445}, {"kind": "rdp", "port": 3389}],
                },
                {
                    "fqdn": "demo-print.demo.test",
                    "address": "10.77.4.201",
                    "role": "printer",
                    "services": [{"kind": "ssh", "port": 22}],
                },
            ],
        }

    def test_no_password_user_or_option_appears_anywhere_in_the_serialised_view(self):
        presets = load_presets(SHIPPED_PRESETS, DEFAULT_SUBNET)
        secrets = {
            secret
            for preset in presets
            for host in preset.hosts
            for account in host.accounts
            for secret in (account.password, account.user)
        }
        assert secrets

        text = json.dumps([preset.public() for preset in presets])

        assert not [secret for secret in secrets if secret in text]
        assert "password" not in text
        assert "accounts" not in text
        assert "options" not in text
        assert "os_banner" not in text


class TestDnsRecords:
    def test_every_host_is_a_name_and_address_pair(self, tmp_path):
        directory = write_presets(
            tmp_path / "presets", valid_preset("first", 200), valid_preset("second", 216)
        )

        records = dns_records(load_presets(directory, "10.77.4.0/24"))

        assert records == [
            ("first-file.demo.test", "10.77.4.200"),
            ("first-print.demo.test", "10.77.4.201"),
            ("second-file.demo.test", "10.77.4.216"),
            ("second-print.demo.test", "10.77.4.217"),
        ]

    def test_the_shipped_presets_give_one_unique_pair_per_host(self):
        presets = load_presets(SHIPPED_PRESETS, DEFAULT_SUBNET)

        records = dns_records(presets)

        assert len(records) == sum(len(preset.hosts) for preset in presets)
        assert len({name for name, _ in records}) == len(records)
        assert len({address for _, address in records}) == len(records)

    def test_no_presets_give_no_records(self):
        assert dns_records([]) == []


class TestConfiguration:
    def test_the_presets_are_where_the_image_puts_them(self):
        assert EngineConfig().lan_presets_dir == Path("/usr/local/lib/tartarus/lan-presets")

    def test_the_environment_can_move_them(self):
        config = EngineConfig.from_environment({"GUEST_LAN_PRESETS_DIR": "/elsewhere"})

        assert config.lan_presets_dir == Path("/elsewhere")
