from enum import StrEnum


class Fault(StrEnum):
    NOT_A_FILE = "not_a_file"
    EMPTY = "empty"
    NOT_AN_ISO = "not_an_iso"
    UNSUPPORTED_FILESYSTEM = "unsupported_filesystem"
    ATTACH_FAILED = "attach_failed"
    TOOL_MISSING = "tool_missing"
    TIMED_OUT = "timed_out"
    UNRECOGNISED = "unrecognised"
    INSPECTION_FAILED = "inspection_failed"


# One table of what the GUI shows for every way a medium can fail to be read. The first two and
# ATTACH_FAILED / TOOL_MISSING are the operator's problem, not the file's, and say so.
MESSAGES: dict[Fault, str] = {
    Fault.NOT_A_FILE: "Not a readable file (a folder or a broken link).",
    Fault.EMPTY: "The file is empty; if it is still being copied, wait and refresh.",
    Fault.NOT_AN_ISO: "Not a disc image that can be read (not an ISO, or damaged).",
    Fault.UNSUPPORTED_FILESYSTEM: (
        "This host cannot read the image's filesystem (is the udf kernel module available?)."
    ),
    Fault.ATTACH_FAILED: (
        "Could not attach the image to a loop device; a problem of the host, not of the file."
    ),
    Fault.TOOL_MISSING: "A tool needed to read the image is not installed in the container.",
    Fault.TIMED_OUT: "Reading the image took too long and was stopped.",
    Fault.UNRECOGNISED: "Not a recognised installation medium.",
    Fault.INSPECTION_FAILED: "The image could not be inspected; see the control service log.",
}


class MediaProblem(Exception):  # noqa: N818 - a problem with one medium, shown to the analyst, not a program error
    """One medium cannot be read; `str()` is the message the GUI shows for it.

    `fault` is one of `Fault` for engine-level problems, or None when an inspector brings its own
    message for what it found inside the medium.
    """

    def __init__(self, fault: Fault | str, *, detail: str | None = None) -> None:
        message = MESSAGES.get(fault, str(fault)) if isinstance(fault, Fault) else fault
        super().__init__(message)
        self.fault = fault
        self.detail = detail
