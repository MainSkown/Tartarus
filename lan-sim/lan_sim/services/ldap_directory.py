"""What the fake directory contains: the root DSE and the domain's own entry, derived from the host.

The names come from `identity`, so LDAP never invents its own: the host's FQDN decides the domain,
and a host that is not a domain controller answers the same way a domain controller does.
"""

from datetime import datetime

from lan_session import HostSpec
from lan_sim.identity import base_dn, dns_domain, netbios_name

Entry = dict[str, list[str]]

# Windows Server 2016 functional level.
FUNCTIONAL_LEVEL = "7"
PAGED_RESULTS_CONTROL = "1.2.840.113556.1.4.319"
ACTIVE_DIRECTORY_CAPABILITIES = [
    "1.2.840.113556.1.4.800",
    "1.2.840.113556.1.4.1670",
    "1.2.840.113556.1.4.1791",
    "1.2.840.113556.1.4.1935",
    "1.2.840.113556.1.4.2080",
    "1.2.840.113556.1.4.2237",
]
# What a Windows domain controller advertises; NTLM is not a SASL mechanism there, it rides in
# GSS-SPNEGO.
SASL_MECHANISMS = ["GSSAPI", "GSS-SPNEGO", "EXTERNAL", "DIGEST-MD5"]
ALL_ATTRIBUTES = "*"
ALL_OPERATIONAL_ATTRIBUTES = "+"
NO_ATTRIBUTES = "1.1"


def root_dse(host: HostSpec, now: datetime) -> Entry:
    base = base_dn(host)
    configuration = f"CN=Configuration,{base}"
    computer = netbios_name(host)
    server = f"CN={computer},CN=Servers,CN=Default-First-Site-Name,CN=Sites,{configuration}"
    return {
        "currentTime": [now.strftime("%Y%m%d%H%M%S.0Z")],
        "dsServiceName": [f"CN=NTDS Settings,{server}"],
        "namingContexts": [base, configuration, f"CN=Schema,{configuration}"],
        "defaultNamingContext": [base],
        "schemaNamingContext": [f"CN=Schema,{configuration}"],
        "configurationNamingContext": [configuration],
        "rootDomainNamingContext": [base],
        "supportedControl": [PAGED_RESULTS_CONTROL],
        "supportedLDAPVersion": ["3", "2"],
        "supportedSASLMechanisms": SASL_MECHANISMS,
        "supportedCapabilities": ACTIVE_DIRECTORY_CAPABILITIES,
        "highestCommittedUSN": ["12345"],
        "dnsHostName": [host.fqdn],
        "ldapServiceName": [f"{dns_domain(host)}:{computer.lower()}$@{dns_domain(host).upper()}"],
        "serverName": [server],
        "isSynchronized": ["TRUE"],
        "isGlobalCatalogReady": ["TRUE"],
        "domainFunctionality": [FUNCTIONAL_LEVEL],
        "forestFunctionality": [FUNCTIONAL_LEVEL],
        "domainControllerFunctionality": [FUNCTIONAL_LEVEL],
    }


def domain_entry(host: HostSpec) -> Entry:
    domain = dns_domain(host).partition(".")[0]
    return {
        "objectClass": ["top", "domain", "domainDNS"],
        "distinguishedName": [base_dn(host)],
        "name": [domain],
        "dc": [domain],
    }


def is_domain_dn(host: HostSpec, dn: str) -> bool:
    return _normalized(dn) == _normalized(base_dn(host))


def select_attributes(entry: Entry, requested: list[str]) -> Entry:
    """The attributes a search asked for; none asked, or `*` or `+`, means all of them."""
    wanted = {name.casefold() for name in requested}
    if not wanted or wanted & {ALL_ATTRIBUTES, ALL_OPERATIONAL_ATTRIBUTES}:
        return entry
    if NO_ATTRIBUTES in wanted:
        return {}
    return {name: values for name, values in entry.items() if name.casefold() in wanted}


def _normalized(dn: str) -> str:
    return ",".join(part.strip().casefold() for part in dn.split(","))
