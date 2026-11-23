"""The names a fake host answers to, derived from its FQDN so no protocol invents its own."""

from lan_session import HostSpec

MAX_NETBIOS_LENGTH = 15


def netbios_name(host: HostSpec) -> str:
    return _netbios(host.fqdn.partition(".")[0])


def dns_domain(host: HostSpec) -> str:
    return host.fqdn.partition(".")[2]


def netbios_domain(host: HostSpec) -> str:
    return _netbios(dns_domain(host).partition(".")[0])


def base_dn(host: HostSpec) -> str:
    return ",".join(f"DC={label}" for label in dns_domain(host).split("."))


def account_for(host: HostSpec, user: str) -> tuple[str, str] | None:
    """The host's (user, password) for `user` as a client writes it: `user`, `DOMAIN\\user` or
    `user@domain`, in any case. The domain part is not checked; the password still has to be."""
    wanted = _bare_user(user).casefold()
    if not wanted:
        return None
    return next((account for account in host.accounts if account[0].casefold() == wanted), None)


def _netbios(label: str) -> str:
    return label.upper()[:MAX_NETBIOS_LENGTH]


def _bare_user(user: str) -> str:
    return user.rpartition("\\")[2].partition("@")[0]
