import logging

from app.config import LogLevel


def configure_logging(level: LogLevel) -> None:
    logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("app").setLevel(level.upper())
    # An unreachable store is already reported by the health check; the client would add a
    # traceback per retry to every poll.
    logging.getLogger("opensearch").setLevel(logging.ERROR)
