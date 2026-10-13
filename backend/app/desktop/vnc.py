VNC_PORT_RANGE = range(5900, 6000)


def vnc_port(options: str | None) -> int | None:
    """The VNC port CAPE recorded in a task's `options`, or None when absent or not a display port.

    CAPE appends its own `vnc_port` after the submitted options, so the last one wins.
    """
    last: str | None = None
    for pair in (options or "").split(","):
        key, separator, value = pair.partition("=")
        if separator and key == "vnc_port":
            last = value
    if last is None or not (last.isascii() and last.isdigit()):
        return None
    port = int(last)
    return port if port in VNC_PORT_RANGE else None
