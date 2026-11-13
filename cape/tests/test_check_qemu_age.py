import importlib.util
import io
import pathlib
import re
import sys
import urllib.error
import urllib.request
from datetime import date

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "check-qemu-age.py"
TODAY = date(2026, 11, 12)


def load():
    spec = importlib.util.spec_from_file_location("check_qemu_age", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


qemu_age = load()

DOCKERFILE = """\
FROM ubuntu:24.04 AS qemu-build
ARG ANTIVM_TABLET_VENDOR=Wacom
ARG QEMU_VERSION=9.2.4
ARG QEMU_SHA256=f3cc1c4eabfdb288218ac3e33763dbe9e276d8bc890b867a2335d58de2ddd39a
"""

RELEASE_RECORD = "# comment\nversion=9.2.4\nreleased=2025-05-28\n"


def listing(*names):
    rows = "".join(
        f'<tr><td><a href="/{name}">{name}</a></td><td>1</td><td>2026-01-01T00:00:00.000Z</td></tr>'
        for name in names
    )
    return (
        f'<html><body><table><tr><td><a href="/old/">old/</a></td></tr>{rows}</table></body></html>'
    )


def tarballs(*versions):
    names = []
    for version in versions:
        names += [f"qemu-{version}.tar.xz", f"qemu-{version}.tar.xz.sig", f"qemu-{version}.tar.bz2"]
    return listing(*names)


# --- reading the pin -----------------------------------------------------------------------


def test_the_pinned_version_is_the_default_of_the_qemu_version_arg():
    assert qemu_age.pinned_version(DOCKERFILE) == "9.2.4"


def test_a_dockerfile_without_the_arg_is_an_error_not_an_empty_pin():
    with pytest.raises(ValueError, match="QEMU_VERSION"):
        qemu_age.pinned_version("FROM ubuntu:24.04\nARG OTHER=1\n")


def test_the_release_record_gives_a_version_and_its_upstream_release_date():
    assert qemu_age.parse_release_record(RELEASE_RECORD) == qemu_age.Release(
        "9.2.4", date(2025, 5, 28)
    )


@pytest.mark.parametrize(
    "text",
    [
        "released=2025-05-28\n",
        "version=9.2.4\n",
        "version=9.2.4\nreleased=28/05/2025\n",
        "version=nine\nreleased=2025-05-28\n",
    ],
)
def test_a_release_record_missing_or_mangling_a_field_is_an_error(text):
    with pytest.raises(ValueError, match="release record"):
        qemu_age.parse_release_record(text)


def test_a_record_for_another_version_than_the_dockerfile_pins_is_an_error():
    record = qemu_age.Release("9.2.3", date(2025, 3, 26))

    with pytest.raises(ValueError, match=r"9\.2\.3.*9\.2\.4"):
        qemu_age.require_matching(record, "9.2.4")


# --- the offline verdict -------------------------------------------------------------------


def test_a_build_at_the_threshold_is_not_stale_and_one_day_past_it_is():
    release = qemu_age.Release("9.2.4", date(2026, 5, 16))

    assert qemu_age.age_days(release, TODAY) == 180
    assert qemu_age.offline_findings(release, TODAY, max_age_days=180) == []
    stale = qemu_age.offline_findings(release, date(2026, 11, 13), max_age_days=180)
    assert [finding.severity for finding in stale] == ["error"]
    assert all(part in stale[0].message for part in ("181 days", "180", "9.2.4"))


# --- reading the download index ------------------------------------------------------------


def test_the_index_yields_one_version_per_tarball_ignoring_signatures_and_other_formats():
    html = tarballs("10.0.15", "11.1.3") + listing(
        "qemu-11.2.0-rc1.tar.xz", "qemu-docs-11.1.3.tar.xz", "qemu-10.2.0.tar.xz"
    )

    assert qemu_age.index_versions(html) == {(10, 0, 15), (11, 1, 3), (10, 2, 0)}


def test_a_four_number_urgent_fix_release_is_read_as_a_later_version_of_its_point_release():
    assert qemu_age.index_versions(tarballs("9.2.4.1")) == {(9, 2, 4, 1)}
    assert (9, 2, 4, 1) > (9, 2, 4)


# --- the online verdict --------------------------------------------------------------------


def test_a_newer_point_release_of_the_pinned_series_is_an_error():
    findings = qemu_age.online_findings("9.2.4", {(9, 2, 4), (9, 2, 5)})

    assert [(f.severity, "9.2.5" in f.message) for f in findings] == [("error", True)]


def test_a_pin_on_the_newest_point_release_of_the_newest_series_has_no_findings():
    assert qemu_age.online_findings("11.1.3", {(11, 1, 2), (11, 1, 3), (10, 2, 4)}) == []


def test_a_newer_series_that_already_has_point_releases_is_a_warning_naming_its_newest_release():
    findings = qemu_age.online_findings("9.2.4", {(9, 2, 4), (10, 2, 4), (11, 1, 1), (11, 1, 3)})

    assert [f.severity for f in findings] == ["warning"]
    assert "11.1.3" in findings[0].message


def test_a_newer_series_with_only_its_first_release_is_not_yet_a_stable_series():
    assert qemu_age.online_findings("11.1.3", {(11, 1, 3), (11, 2, 0)}) == []


def test_newer_point_releases_of_the_series_are_found_by_probing_past_a_truncated_index():
    existing = {"qemu-9.2.5.tar.xz", "qemu-9.2.6.tar.xz"}

    found = qemu_age.probe_series_releases("9.2.4", lambda name: name in existing)

    assert found == {(9, 2, 5), (9, 2, 6)}


def test_probing_finds_nothing_when_the_next_point_release_does_not_exist():
    assert qemu_age.probe_series_releases("9.2.4", lambda _name: False) == set()


# --- the network ---------------------------------------------------------------------------


def test_a_redirect_to_another_host_is_refused():
    handler = qemu_age.SameHostRedirects()
    request = urllib.request.Request("https://download.qemu.org/")

    refused = handler.redirect_request(
        request, io.BytesIO(), 302, "Found", {}, "https://evil.example/"
    )
    followed = handler.redirect_request(
        request, io.BytesIO(), 301, "Moved", {}, "https://download.qemu.org/index"
    )

    assert refused is None
    assert followed is not None


def test_a_response_larger_than_the_cap_is_an_error_not_an_unbounded_read():
    with pytest.raises(OSError, match="larger than"):
        qemu_age.read_capped(io.BytesIO(b"x" * 11), limit=10)


# --- the command ---------------------------------------------------------------------------


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "cape" / "build").mkdir(parents=True)
    (tmp_path / "cape" / "Dockerfile").write_text(DOCKERFILE)
    (tmp_path / "cape" / "build" / "qemu-release").write_text(RELEASE_RECORD)
    return tmp_path


def run(repo, *args, fetch=None, exists=None):
    out = io.StringIO()
    code = qemu_age.main(
        ["--root", str(repo), *args], today=TODAY, fetch=fetch, exists=exists, out=out
    )
    return code, out.getvalue()


def test_offline_it_fails_on_a_stale_pin_and_always_prints_version_age_and_threshold(repo):
    code, output = run(repo)

    assert code == 1
    assert all(part in output for part in ("9.2.4", "533 days", "180"))


def test_offline_it_passes_a_fresh_pin(repo):
    (repo / "cape" / "build" / "qemu-release").write_text("version=9.2.4\nreleased=2026-10-01\n")

    code, output = run(repo)

    assert code == 0
    assert all(part in output for part in ("9.2.4", "42 days"))


def test_the_threshold_can_be_given_on_the_command_line(repo):
    code, _ = run(repo, "--max-age-days", "1000")

    assert code == 0


def test_a_record_that_disagrees_with_the_dockerfile_is_a_configuration_error(repo):
    (repo / "cape" / "build" / "qemu-release").write_text("version=9.2.3\nreleased=2025-03-26\n")

    code, output = run(repo)

    assert code == 2
    assert all(part in output for part in ("9.2.3", "9.2.4"))


def test_online_a_newer_point_release_fails_even_when_the_pin_is_young(repo):
    (repo / "cape" / "build" / "qemu-release").write_text("version=9.2.4\nreleased=2026-10-01\n")

    code, output = run(
        repo,
        "--online",
        fetch=lambda _url: tarballs("9.2.4"),
        exists=lambda name: name == "qemu-9.2.5.tar.xz",
    )

    assert code == 1
    assert "9.2.5" in output


def test_online_a_newer_series_is_a_warning_that_does_not_fail_a_young_pin(repo):
    (repo / "cape" / "build" / "qemu-release").write_text("version=9.2.4\nreleased=2026-10-01\n")

    code, output = run(
        repo,
        "--online",
        fetch=lambda _url: tarballs("11.1.1", "11.1.3"),
        exists=lambda _name: False,
    )

    assert code == 0
    assert all(part in output for part in ("warning", "11.1.3"))


def test_online_a_network_failure_is_a_distinct_exit_with_a_message_not_a_traceback(repo):
    def broken(url):
        raise urllib.error.URLError("name resolution failed")

    code, output = run(repo, "--online", fetch=broken, exists=lambda _name: False)

    assert code == 3
    assert all(part in output for part in ("download.qemu.org", "name resolution failed"))
    assert "Traceback" not in output


def test_offline_never_touches_the_network(repo):
    def forbidden(url):
        raise AssertionError("offline mode fetched " + url)

    code, _ = run(repo, fetch=forbidden, exists=forbidden)

    assert code == 1


# --- the pin as the repo has it ------------------------------------------------------------


def test_the_release_record_in_the_repo_matches_the_dockerfile_default():
    dockerfile = (REPO / "cape" / "Dockerfile").read_text()
    record = qemu_age.parse_release_record((REPO / "cape" / "build" / "qemu-release").read_text())

    qemu_age.require_matching(record, qemu_age.pinned_version(dockerfile))


def test_the_dockerfile_pins_a_sha256_for_the_tarball():
    dockerfile = (REPO / "cape" / "Dockerfile").read_text()

    assert re.search(r"^ARG QEMU_SHA256=[0-9a-f]{64}$", dockerfile, re.MULTILINE)


def qemu_build_stage():
    dockerfile = (REPO / "cape" / "Dockerfile").read_text()
    start = dockerfile.index("AS qemu-build")
    return dockerfile[start : dockerfile.index("AS guacd-build")]


def test_the_tarball_is_checked_against_the_pin_before_the_installer_compiles_it():
    stage = qemu_build_stage()

    assert "sha256sum -c" in stage
    assert stage.index("sha256sum -c") < stage.index("kvm-qemu.sh qemu")


def test_the_installer_is_told_the_version_through_the_config_it_sources():
    config = (REPO / "cape" / "build" / "kvm-config.sh").read_text()

    assert re.search(r'^qemu_version="\$\{?QEMU_VERSION', config, re.MULTILINE)


def test_the_build_fails_when_the_installed_qemu_is_not_the_pinned_version():
    stage = qemu_build_stage()

    assert re.search(r"qemu-system-x86_64 --version.*QEMU_VERSION", stage)
