import pytest

from lan_session import HostSpec
from lan_sim.identity import account_for, base_dn, dns_domain, netbios_domain, netbios_name


def host(
    fqdn="fs01.corp.local", accounts=(("Administrator", "P@ss1"), ("svc_backup", "Backup2020"))
):
    return HostSpec(fqdn, "192.168.150.200", "Windows", accounts, ())


def test_the_netbios_name_is_the_first_label_in_upper_case():
    assert netbios_name(host()) == "FS01"


def test_a_netbios_name_is_cut_to_fifteen_characters():
    assert netbios_name(host("a-very-long-host-name-01.corp.local")) == "A-VERY-LONG-HOS"


def test_the_dns_domain_is_the_fqdn_without_its_first_label():
    assert dns_domain(host()) == "corp.local"
    assert dns_domain(host("dc01.eu.corp.local")) == "eu.corp.local"


def test_the_netbios_domain_is_the_first_label_of_the_dns_domain_in_upper_case():
    assert netbios_domain(host()) == "CORP"
    assert netbios_domain(host("dc01.eu.corp.local")) == "EU"


def test_a_netbios_domain_is_cut_to_fifteen_characters():
    assert netbios_domain(host("fs01.a-very-long-domain-name.local")) == "A-VERY-LONG-DOM"


def test_the_base_dn_has_one_dc_component_per_dns_domain_label():
    assert base_dn(host()) == "DC=corp,DC=local"
    assert base_dn(host("dc01.eu.corp.local")) == "DC=eu,DC=corp,DC=local"


@pytest.mark.parametrize(
    "user",
    [
        "Administrator",
        "administrator",
        "ADMINISTRATOR",
        "CORP\\Administrator",
        "corp\\administrator",
        "FS01\\Administrator",
        "Administrator@corp.local",
        "administrator@CORP",
    ],
)
def test_account_for_finds_the_account_in_every_form_a_client_sends(user):
    assert account_for(host(), user) == ("Administrator", "P@ss1")


def test_account_for_returns_the_stored_spelling_and_password_of_the_matching_account():
    assert account_for(host(), "SVC_BACKUP") == ("svc_backup", "Backup2020")


@pytest.mark.parametrize(
    "user", ["", "nobody", "CORP\\", "\\", "@corp.local", "Administrator ", "Administrator2", "@"]
)
def test_account_for_knows_nobody_else(user):
    assert account_for(host(), user) is None


def test_account_for_on_a_host_without_accounts_is_none():
    assert account_for(host(accounts=()), "Administrator") is None


def test_account_for_does_not_match_a_user_by_prefix_or_by_the_domain_part():
    assert account_for(host(), "Admin") is None
    assert account_for(host(), "Administrator\\other") is None
    assert account_for(host(), "other@Administrator") is None


def test_a_password_is_returned_even_when_it_is_empty():
    assert account_for(host(accounts=(("guest", ""),)), "GUEST") == ("guest", "")
