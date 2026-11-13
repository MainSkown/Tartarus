"""Fail when the QEMU or the libvirt the cape image is built from source with has aged out.

Each version is pinned in one place, the `ARG QEMU_VERSION=` and `ARG LIBVIRT_VERSION=` defaults in
cape/Dockerfile. cape/build/qemu-release and cape/build/libvirt-release record those versions'
upstream release dates, and pin and record must agree or the check stops with a configuration error.

Offline (default): exit 1 when the pinned release is older than --max-age-days (180 by default: the
maintained series ship a point release every one to two months, so half a year without one means the
build missed several security rollups or its series has ended). Online (--online): also exit 1 when
download.qemu.org has a newer point release of the pinned series, and warn when a newer series
already has point releases. libvirt has no point releases (one release a month), so its age is the
whole check.

Exit codes: 0 fine (warnings allowed), 1 stale or behind upstream, 2 the pin or the record is
unreadable or they disagree, 3 download.qemu.org could not be read.

The directory index lists at most 1000 files alphabetically, so releases of old series (9.x and
below at the time of writing) are cut off its end. The pinned series' later point releases are
therefore probed by name instead of read from the index.
"""

from __future__ import annotations

import argparse
import http.client
import re
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TextIO
from urllib.parse import urlsplit

INDEX_URL = "https://download.qemu.org/"
DEFAULT_MAX_AGE_DAYS = 180
USER_AGENT = "qemu-age-check/1.0"
TIMEOUT_SECONDS = 20
MAX_INDEX_BYTES = 4 * 1024 * 1024

Version = tuple[int, ...]

TARBALL_LINK = re.compile(r'href="/?qemu-(\d+(?:\.\d+){2,3})\.tar\.xz"')
VERSION = re.compile(r"\d+\.\d+\.\d+")


@dataclass(frozen=True)
class Source:
    name: str
    version_arg: str
    record_file: str


QEMU = Source("QEMU", "QEMU_VERSION", "qemu-release")
LIBVIRT = Source("libvirt", "LIBVIRT_VERSION", "libvirt-release")


@dataclass(frozen=True)
class Release:
    version: str
    released: date


@dataclass(frozen=True)
class Finding:
    severity: str
    message: str


def version_tuple(version: str) -> Version:
    return tuple(int(part) for part in version.split("."))


def pinned_version(dockerfile: str, source: Source = QEMU) -> str:
    match = re.search(rf"^ARG {source.version_arg}=(\d+\.\d+\.\d+)\s*$", dockerfile, re.MULTILINE)
    if not match:
        raise ValueError(
            f"cape/Dockerfile has no 'ARG {source.version_arg}=<major.minor.patch>' line"
        )
    return match.group(1)


def parse_release_record(text: str) -> Release:
    fields = dict(
        line.split("=", 1)
        for line in (raw.strip() for raw in text.splitlines())
        if line and not line.startswith("#") and "=" in line
    )
    if not VERSION.fullmatch(fields.get("version", "")):
        raise ValueError("the release record needs a 'version=<major.minor.patch>' line")
    try:
        released = date.fromisoformat(fields.get("released", ""))
    except ValueError:
        raise ValueError("the release record needs a 'released=YYYY-MM-DD' line") from None
    return Release(fields["version"], released)


def require_matching(record: Release, pinned: str, source: Source = QEMU) -> None:
    if record.version != pinned:
        raise ValueError(
            f"cape/build/{source.record_file} records {record.version} but cape/Dockerfile pins "
            f"{pinned}; update them together"
        )


def pinned_release(root: Path, source: Source) -> Release:
    pinned = pinned_version((root / "cape" / "Dockerfile").read_text(), source)
    release = parse_release_record((root / "cape" / "build" / source.record_file).read_text())
    require_matching(release, pinned, source)
    return release


def age_days(release: Release, today: date) -> int:
    return (today - release.released).days


def offline_findings(
    release: Release, today: date, max_age_days: int, source: Source = QEMU
) -> list[Finding]:
    age = age_days(release, today)
    if age <= max_age_days:
        return []
    return [
        Finding(
            "error",
            f"{source.name} {release.version} was released {release.released} ({age} days ago), "
            f"over the {max_age_days} day limit: bump it (see 'Updating QEMU and libvirt' in "
            "docs/specs/cape-integration.md)",
        )
    ]


def index_versions(index_html: str) -> set[Version]:
    return {version_tuple(version) for version in TARBALL_LINK.findall(index_html)}


def probe_series_releases(pinned: str, exists: Callable[[str], bool]) -> set[Version]:
    major, minor, patch = version_tuple(pinned)
    found: set[Version] = set()
    while exists(f"qemu-{major}.{minor}.{patch + 1}.tar.xz"):
        patch += 1
        found.add((major, minor, patch))
    return found


def dotted(version: Version) -> str:
    return ".".join(map(str, version))


def online_findings(pinned: str, available: set[Version]) -> list[Finding]:
    pin = version_tuple(pinned)
    series = pin[:2]
    findings: list[Finding] = []
    newer_in_series = [version for version in available if version[:2] == series and version > pin]
    if newer_in_series:
        findings.append(
            Finding(
                "error",
                f"QEMU {dotted(max(newer_in_series))} is out, a newer point release of the pinned "
                f"{dotted(series)} series: rebuild with it",
            )
        )
    newer_stable = [version for version in available if version[:2] > series and version[2] >= 1]
    if newer_stable:
        newest = max(newer_stable)
        findings.append(
            Finding(
                "warning",
                f"series {dotted(newest[:2])} (newest release {dotted(newest)}) is newer than the "
                f"pinned {dotted(series)}, which may no longer get point releases",
            )
        )
    return findings


class SameHostRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: PLR0913, PLR0917
        target, origin = urlsplit(newurl), urlsplit(req.full_url)
        if target.scheme != "https" or target.hostname != origin.hostname:
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def read_capped(stream, limit: int = MAX_INDEX_BYTES) -> bytes:
    data = stream.read(limit + 1)
    if len(data) > limit:
        raise OSError(f"response is larger than {limit} bytes")
    return data


def open_url(url: str, method: str = "GET"):
    opener = urllib.request.build_opener(SameHostRedirects)
    request = urllib.request.Request(  # noqa: S310 - only INDEX_URL-based https URLs reach here
        url, method=method, headers={"User-Agent": USER_AGENT}
    )
    return opener.open(request, timeout=TIMEOUT_SECONDS)


def fetch_index(url: str) -> str:
    with open_url(url) as response:
        return read_capped(response).decode("utf-8", errors="replace")


def tarball_exists(name: str) -> bool:
    try:
        with open_url(INDEX_URL + name, method="HEAD"):
            return True
    except urllib.error.HTTPError as error:
        if error.code == http.HTTPStatus.NOT_FOUND:
            return False
        raise


def parse_arguments(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fail when the pinned QEMU or libvirt build is stale."
    )
    parser.add_argument("--online", action="store_true", help=f"also compare with {INDEX_URL}")
    parser.add_argument("--max-age-days", type=int, default=DEFAULT_MAX_AGE_DAYS)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    return parser.parse_args(argv)


def main(
    argv: list[str],
    *,
    today: date | None = None,
    fetch: Callable[[str], str] | None = None,
    exists: Callable[[str], bool] | None = None,
    out: TextIO | None = None,
) -> int:
    out = out or sys.stdout
    today = today or date.today()
    arguments = parse_arguments(argv)
    try:
        releases = {source: pinned_release(arguments.root, source) for source in (QEMU, LIBVIRT)}
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=out)
        return 2

    findings: list[Finding] = []
    for source, release in releases.items():
        print(
            f"pinned {source.name} {release.version}, released {release.released}, "
            f"{age_days(release, today)} days old, limit {arguments.max_age_days} days",
            file=out,
        )
        findings += offline_findings(release, today, arguments.max_age_days, source)
    pinned = releases[QEMU].version
    if arguments.online:
        try:
            probe = exists or tarball_exists
            available = index_versions((fetch or fetch_index)(INDEX_URL)) | probe_series_releases(
                pinned, probe
            )
        except (OSError, http.client.HTTPException) as error:
            print(f"error: cannot read {INDEX_URL}: {error}", file=out)
            return 3
        findings += online_findings(pinned, available)

    for finding in findings:
        print(f"{finding.severity}: {finding.message}", file=out)
    if not findings:
        print("ok", file=out)
    return 1 if any(finding.severity == "error" for finding in findings) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
