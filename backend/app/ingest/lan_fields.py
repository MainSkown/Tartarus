"""The `tartarus.lan.*` fields of an event that involves the fake local network."""

from typing import Any

from app.ingest.protocol import LanHost


def lan_section(fake_host: LanHost | None = None, /, **fields: Any) -> dict[str, Any]:
    """The `tartarus` fields of an event on the fake LAN: `fake_host` gives the host's name, role
    and preset when the event has one, `fields` adds (or overrides) the event's own.
    """
    named = (
        {}
        if fake_host is None
        else {"host": fake_host.fqdn, "role": fake_host.role, "preset": fake_host.preset}
    )
    return {"lan": {"simulated": True, **named, **fields}}
