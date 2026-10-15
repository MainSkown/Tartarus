"""Recognises Windows installation media: an ISO with sources/install.wim or install.esd.

Loaded by the guest engine as the media inspector of the Windows profile (decision 17). The image
is mounted read-only and `wiminfo` reads the mounted file (S0a: about 40 ms, nothing extracted).
"""

from pathlib import Path
from typing import Any

from guest_engine.media.errors import MediaProblem
from guest_engine.media.inspector import MediaContext

needs_mount = True

WIMINFO_TIMEOUT_S = 60
INSTALL_IMAGES = ("install.wim", "install.esd")

# wiminfo prints its own architecture names; Windows' answer file spells them this way.
ARCHITECTURES = {"x86_64": "amd64", "x86": "x86", "ARM64": "arm64", "ARM": "arm", "IA64": "ia64"}

# What the GUI shows per `wiminfo` exit status seen in S0a; stderr is for the log, not the UI.
WIMINFO_FAILURES = {
    43: "{file} is not a valid Windows image.",
    50: "The image is incomplete or unreadable; is the file still being copied?",
    65: "{file} is damaged or incomplete.",
}
UNLISTED_WIMINFO_FAILURE = "{file} could not be read."
NO_INSTALL_IMAGE = "This looks like Windows media but has no install.wim or install.esd."
NO_WINDOWS_METADATA = "The install image has no Windows version information."


def inspect(path: Path, context: MediaContext) -> dict[str, Any] | None:
    with context.mounted(path) as root:
        sources = root / "sources"
        install_image = next((sources / n for n in INSTALL_IMAGES if (sources / n).is_file()), None)
        if install_image is None:
            if (sources / "boot.wim").is_file():
                raise MediaProblem(NO_INSTALL_IMAGE)
            return None
        parsed = parse_wiminfo(_wiminfo(install_image, context))
    windows_images = [image for image in parsed["images"] if _is_windows(image)]
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
        "compression": parsed["compression"],
    }


def parse_wiminfo(text: str) -> dict[str, Any]:
    """Parse the text form of `wiminfo FILE` into `{compression, image_count, images: [...]}`."""
    header_text, _, images_text = text.partition("Available Images:")
    header = _fields(header_text.splitlines())
    return {
        "compression": header.get("Compression"),
        "image_count": int(header["Image Count"]) if "Image Count" in header else 0,
        "images": [_image(block) for block in _image_blocks(images_text)],
    }


def _wiminfo(install_image: Path, context: MediaContext) -> str:
    result = context.runner(["wiminfo", str(install_image)], timeout=WIMINFO_TIMEOUT_S)
    if result.returncode != 0:
        message = WIMINFO_FAILURES.get(result.returncode, UNLISTED_WIMINFO_FAILURE)
        raise MediaProblem(message.format(file=install_image.name), detail=result.stderr)
    return result.stdout


def _is_windows(image: dict[str, Any]) -> bool:
    return image["edition_id"] is not None and image["build"] is not None


def _variant(image: dict[str, Any]) -> dict[str, Any]:
    keys = ("index", "name", "edition_id", "arch", "languages", "default_language", "build")
    return {**{key: image[key] for key in keys}, "installation_type": image["installation_type"]}


def _image_blocks(images_text: str) -> list[list[str]]:
    blocks: list[list[str]] = []
    for line in images_text.splitlines():
        if line.startswith("Index:"):
            blocks.append([])
        if blocks:
            blocks[-1].append(line)
    return blocks


def _fields(lines: list[str]) -> dict[str, str]:
    fields = {}
    for line in lines:
        key, separator, value = line.partition(":")
        if separator:
            fields[key.strip()] = value.strip()
    return fields


def _image(block: list[str]) -> dict[str, Any]:
    fields = _fields(block)
    build = fields.get("Build")
    return {
        "index": int(fields["Index"]),
        "name": fields.get("Name"),
        "edition_id": fields.get("Edition ID"),
        "arch": _architecture(fields.get("Architecture")),
        "languages": fields.get("Languages", "").split(),
        "default_language": fields.get("Default Language"),
        "build": int(build) if build else None,
        "version": _version(fields),
        "installation_type": fields.get("Installation Type"),
    }


def _architecture(printed: str | None) -> str | None:
    if printed is None:
        return None
    return ARCHITECTURES.get(printed, printed.lower())


def _version(fields: dict[str, str]) -> str | None:
    if not {"Major Version", "Minor Version", "Build"} <= fields.keys():
        return None
    return f"{fields['Major Version']}.{fields['Minor Version']}.{fields['Build']}"
