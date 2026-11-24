"""Asks the guest control service for fake-LAN sessions with the backend's own client.

    python - health | presets | list | open KEY GUEST PRESET | close KEY      (stdin: this file)

verify-isolation.sh opens a session the way the backend does before an analysis, through
`app.guest.client.HttpGuestControl`, so the check covers the request the backend really sends.
It runs in a throwaway container of the backend image on the control network, with the working
tree's `backend/app` mounted over the image's copy; GUEST_CONTROL_URL and GUEST_CONTROL_TOKEN are
the backend's own settings. `presets` prints `preset;address;port;kind` per service, `health`
prints `ready` or the reason, `list` prints the open keys, one per line.
"""

import asyncio
import os
import sys

from app.guest.client import HttpGuestControl
from app.guest.errors import GuestControlError

USAGE = {"health": 0, "presets": 0, "list": 0, "open": 3, "close": 1}


async def run(control: HttpGuestControl, command: str, arguments: list[str]) -> None:
    if command == "health":
        health = await control.lan_health()
        print("ready" if health.ready else health.reason or "not ready")
    elif command == "presets":
        for preset in await control.lan_presets():
            for host in preset.hosts:
                for service in host.services:
                    print(f"{preset.id};{host.address};{service.port};{service.kind}")
    elif command == "list":
        for key in await control.lan_sessions():
            print(key)
    elif command == "open":
        await control.open_lan_session(*arguments)
        print(f"opened {arguments[0]}")
    else:
        copied = await control.close_lan_session(arguments[0])
        print(f"closed {arguments[0]} (log copied: {copied})")


async def main(command: str, arguments: list[str]) -> int:
    async with HttpGuestControl(
        os.environ["GUEST_CONTROL_URL"], os.environ["GUEST_CONTROL_TOKEN"]
    ) as control:
        try:
            await run(control, command, arguments)
        except GuestControlError as refused:
            print(refused, file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2 or USAGE.get(sys.argv[1]) != len(sys.argv) - 2:  # noqa: PLR2004
        raise SystemExit(__doc__)
    raise SystemExit(asyncio.run(main(sys.argv[1], sys.argv[2:])))
