import logging
from collections.abc import Iterator

import pytest

from app.config import LogLevel
from app.logging_config import configure_logging


@pytest.fixture(autouse=True)
def restore_app_logger() -> Iterator[None]:
    loggers = [logging.getLogger("app"), logging.getLogger("opensearch")]
    previous = [logger.level for logger in loggers]
    yield
    for logger, level in zip(loggers, previous, strict=True):
        logger.setLevel(level)


@pytest.mark.parametrize(
    ("name", "level"), [("debug", logging.DEBUG), ("warning", logging.WARNING)]
)
def test_sets_the_app_logger_level(name: LogLevel, level: int) -> None:
    configure_logging(name)

    assert logging.getLogger("app").level == level


def test_opensearch_client_connection_warnings_are_silenced() -> None:
    configure_logging("debug")

    assert logging.getLogger("opensearch").level == logging.ERROR
