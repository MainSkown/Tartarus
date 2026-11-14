"""Recognises Windows installation media: an ISO with sources/install.wim or install.esd.

Loaded by the guest engine as the media inspector of the Windows profile (decision 17). Nothing is
mounted: `wim_reader.py`, beside this file, reads the image's metadata straight out of the ISO in
the engine's unprivileged child process, and this module turns what it found into the result the
wizard lists, or into the message of what is wrong with the medium.
"""

from pathlib import Path
from typing import Any

from guest_engine.media.errors import MediaProblem
from guest_engine.media.inspector import MediaContext

READER = Path(__file__).with_name("wim_reader.py")

# What the GUI shows per way the install image can fail to be read (the codes of wim_reader.py).
IMAGE_FAILURES = {
    "not_a_wim": "{file} is not a valid Windows image.",
    "incomplete": "The image is incomplete or unreadable; is the file still being copied?",
    "damaged": "{file} is damaged or incomplete.",
    "unreadable": "{file} could not be read.",
}
UNLISTED_IMAGE_FAILURE = "{file} could not be read."
NO_INSTALL_IMAGE = "This looks like Windows media but has no install.wim or install.esd."
NO_WINDOWS_METADATA = "The install image has no Windows version information."


def inspect(path: Path, context: MediaContext) -> dict[str, Any] | None:
    found = context.read_inside(path, READER)
    if found["file"] is None:
        if found["boot_wim"]:
            raise MediaProblem(NO_INSTALL_IMAGE)
        return None
    if "failure" in found:
        message = IMAGE_FAILURES.get(found["failure"], UNLISTED_IMAGE_FAILURE)
        raise MediaProblem(message.format(file=found["file"]))
    windows_images = [image for image in found["images"] if _is_windows(image)]
    if not windows_images:
        raise MediaProblem(NO_WINDOWS_METADATA)
    first = windows_images[0]
    return {
        "kind": "installer",
        "variants": [_variant(image) for image in windows_images],
        "version": first["version"],
        "build": first["build"],
        "language": first["default_language"],
        "arch": first["arch"],
        "compression": found["compression"],
    }


def _is_windows(image: dict[str, Any]) -> bool:
    return image["edition_id"] is not None and image["build"] is not None


def _variant(image: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "index",
        "name",
        "edition_id",
        "arch",
        "languages",
        "default_language",
        "build",
        "installation_type",
    )
    return {key: image[key] for key in keys}
