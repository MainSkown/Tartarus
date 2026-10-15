import pytest

from guest_engine.errors import Conflict, GuestNotFound, InvalidParameters


def test_invalid_parameters_message_names_every_field():
    error = InvalidParameters({"name": "already exists", "ram_mb": "too small"})

    assert error.fields == {"name": "already exists", "ram_mb": "too small"}
    assert "name: already exists" in str(error)
    assert "ram_mb: too small" in str(error)


@pytest.mark.parametrize("error", [GuestNotFound("win9"), Conflict("an analysis is running")])
def test_engine_errors_carry_their_message(error):
    assert str(error)
