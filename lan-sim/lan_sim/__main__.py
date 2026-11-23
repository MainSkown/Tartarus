"""Entry point: `python -m lan_sim`. The root directory comes from `LAN_SIM_ROOT`."""

import asyncio
import json
import logging
import os
import signal
import sys
from datetime import UTC, datetime
from pathlib import Path

from lan_session import DEFAULT_ROOT, Layout
from lan_sim.daemon import DEFAULT_POLL_INTERVAL_S, Daemon
from lan_sim.events import sanitize_text
from lan_sim.service import Service

MAX_LOG_MESSAGE_LENGTH = 500


def build_registry() -> dict[str, Service]:
    """The services the daemon can serve, by kind; each protocol adds one line here."""
    return {}


class JsonLineFormatter(logging.Formatter):
    """One JSON object per line: only the message, never an exception's text or a traceback."""

    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {
                "time": datetime.fromtimestamp(record.created, UTC).isoformat(
                    timespec="milliseconds"
                ),
                "level": record.levelname,
                "message": sanitize_text(record.getMessage(), MAX_LOG_MESSAGE_LENGTH),
            }
        )


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonLineFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)


async def serve(layout: Layout, poll_interval: float) -> None:
    daemon = Daemon(layout, build_registry(), poll_interval=poll_interval)
    loop = asyncio.get_running_loop()
    for stop_signal in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(stop_signal, daemon.request_stop)
    await daemon.run()


def main() -> None:
    configure_logging()
    root = Path(os.environ.get("LAN_SIM_ROOT", DEFAULT_ROOT))
    poll_interval = float(os.environ.get("LAN_SIM_POLL_SECONDS", DEFAULT_POLL_INTERVAL_S))
    asyncio.run(serve(Layout(root), poll_interval))


if __name__ == "__main__":
    main()
