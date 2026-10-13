import pytest

from app.desktop.vnc import vnc_port


@pytest.mark.parametrize(
    ("options", "expected"),
    [
        ("interactive=1,vnc_port=5900", 5900),
        ("vnc_port=5900", 5900),
        ("vnc_port=5901,interactive=1", 5901),
        ("vnc_port=5900,vnc_port=5903", 5903),
        ("vnc_port=5903,vnc_port=garbage", None),
        ("vnc_port=5903,vnc_port=80", None),
        ("vnc_port=5899", None),
        ("vnc_port=6000", None),
        ("vnc_port=5999", 5999),
        ("vnc_port=", None),
        ("vnc_port", None),
        ("vnc_port=59 00", None),
        ("vnc_port=5900.0", None),
        ("vnc_port=-5900", None),
        ("vnc_port=+5900", None),
        ("xvnc_port=5900", None),
        ("interactive=1", None),
        ("a=b=c,vnc_port=5902", 5902),
        (",,,", None),
        ("", None),
        (None, None),
    ],
)
def test_vnc_port_is_the_last_vnc_port_option_inside_the_display_range(
    options: str | None, expected: int | None
) -> None:
    assert vnc_port(options) == expected
