import io
import re
from pathlib import Path

import pytest
import pyzipper

from tests.integration.views.conftest import ViewStack
from tests.integration.views.findings.support import install_report, put_file
from tests.integration.views.helpers import get_view

pytestmark = pytest.mark.integration

DROPPED_SHA256 = "19e19f9e997696d63c3a2ef193633c001b032b3880fd4b487dfea606aa77c196"
DROPPED_BYTES = b"tartarus benign sample was here\n"
PASSWORD = b"infected"


def unzip(content: bytes, password: bytes | None) -> dict[str, bytes]:
    with pyzipper.AESZipFile(io.BytesIO(content)) as archive:
        if password:
            archive.setpassword(password)
        return {name: archive.read(name) for name in archive.namelist()}


async def dropped_id(stack: ViewStack) -> str:
    install_report(stack)
    put_file(stack, f"files/{DROPPED_SHA256}", DROPPED_BYTES)
    return str((await get_view(stack, "artifacts"))["dropped"][0]["id"])


async def test_a_download_is_a_zip_that_opens_with_the_password_and_holds_the_bytes(
    stack: ViewStack,
) -> None:
    artifact_id = await dropped_id(stack)

    response = await stack.client.get(
        f"/api/analyses/{stack.analysis_id}/artifacts/{artifact_id}/download"
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert 'filename="tartarus-benign.txt.zip"' in response.headers["content-disposition"]
    assert unzip(response.content, PASSWORD) == {"tartarus-benign.txt": DROPPED_BYTES}


async def test_the_zip_does_not_open_without_the_password_or_with_another(
    stack: ViewStack,
) -> None:
    artifact_id = await dropped_id(stack)
    response = await stack.client.get(
        f"/api/analyses/{stack.analysis_id}/artifacts/{artifact_id}/download"
    )

    with pytest.raises(RuntimeError):
        unzip(response.content, None)
    with pytest.raises(RuntimeError):
        unzip(response.content, b"wrong")
    assert DROPPED_BYTES not in response.content


async def test_a_download_leaves_no_temporary_zip_behind(
    stack: ViewStack, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path / "scratch"))
    (tmp_path / "scratch").mkdir()
    artifact_id = await dropped_id(stack)

    await stack.client.get(f"/api/analyses/{stack.analysis_id}/artifacts/{artifact_id}/download")

    assert list((tmp_path / "scratch").iterdir()) == []


async def test_the_file_name_in_the_download_header_cannot_break_out_of_it(
    stack: ViewStack,
) -> None:
    report = install_report(stack)
    report["dropped"][0]["name"] = ['we"ird\r\nname.txt']
    install_report(stack, report)
    put_file(stack, f"files/{DROPPED_SHA256}", DROPPED_BYTES)
    artifact_id = (await get_view(stack, "artifacts"))["dropped"][0]["id"]

    response = await stack.client.get(
        f"/api/analyses/{stack.analysis_id}/artifacts/{artifact_id}/download"
    )

    disposition = response.headers["content-disposition"]
    assert "\r" not in disposition
    assert "\n" not in disposition
    assert disposition.count('"') == 2
    assert list(unzip(response.content, PASSWORD)) == ["we_ird__name.txt"]


async def test_an_artifact_whose_file_is_gone_is_a_404(stack: ViewStack) -> None:
    install_report(stack)
    artifact_id = (await get_view(stack, "artifacts"))["dropped"][0]["id"]

    response = await stack.client.get(
        f"/api/analyses/{stack.analysis_id}/artifacts/{artifact_id}/download"
    )

    assert response.status_code == 404


@pytest.mark.parametrize(
    "artifact_id",
    [
        "../../etc/passwd",
        "..%2F..%2Fetc%2Fpasswd",
        "%2e%2e%2f%2e%2e%2fetc%2fpasswd",
        "%2e%2e",
        "..",
        "/etc/passwd",
        "%2Fetc%2Fpasswd",
        "....//....//etc/passwd",
        "..\\..\\windows\\win.ini",
        DROPPED_SHA256,
        f"files/{DROPPED_SHA256}",
        "secret.txt",
        "%00",
        "does-not-exist",
    ],
)
async def test_an_id_that_is_not_in_the_artifact_list_is_a_404_and_reads_nothing(
    stack: ViewStack, tmp_path: Path, artifact_id: str
) -> None:
    await dropped_id(stack)
    secret = tmp_path / "secret.txt"
    secret.write_bytes(b"outside the storage root")

    response = await stack.client.get(
        f"/api/analyses/{stack.analysis_id}/artifacts/{artifact_id}/download"
    )

    assert response.status_code == 404
    assert b"outside the storage root" not in response.content
    assert b"root:" not in response.content


async def test_a_report_naming_a_path_outside_the_storage_cannot_make_it_downloadable(
    stack: ViewStack, tmp_path: Path
) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_bytes(b"outside the storage root")
    report = install_report(stack)
    report["dropped"][0]["path"] = str(secret)
    report["dropped"][0]["sha256"] = "../../../../secret.txt"
    install_report(stack, report)

    listed = (await get_view(stack, "artifacts"))["dropped"][0]
    response = await stack.client.get(
        f"/api/analyses/{stack.analysis_id}/artifacts/{listed['id']}/download"
    )

    assert listed["downloadable"] is False
    assert response.status_code == 404


async def test_a_link_in_the_analysis_folder_to_a_file_outside_is_not_served(
    stack: ViewStack, tmp_path: Path
) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_bytes(b"outside the storage root")
    install_report(stack)
    link = stack.analysis_dir / "files" / DROPPED_SHA256
    link.parent.mkdir()
    link.symlink_to(secret)
    artifact_id = (await get_view(stack, "artifacts"))["dropped"][0]["id"]

    response = await stack.client.get(
        f"/api/analyses/{stack.analysis_id}/artifacts/{artifact_id}/download"
    )

    assert response.status_code == 404
    assert b"outside the storage root" not in response.content


async def test_a_download_of_an_unknown_analysis_is_a_404(stack: ViewStack) -> None:
    response = await stack.client.get("/api/analyses/99999/artifacts/abc/download")

    assert response.status_code == 404


async def test_the_pcap_downloads_as_a_zip_through_the_artifact_route(stack: ViewStack) -> None:
    install_report(stack)
    put_file(stack, "dump.pcap", b"pcap-bytes")
    artifact_id = (await get_view(stack, "artifacts"))["pcap"]["id"]

    response = await stack.client.get(
        f"/api/analyses/{stack.analysis_id}/artifacts/{artifact_id}/download"
    )

    assert unzip(response.content, PASSWORD) == {"dump.pcap": b"pcap-bytes"}


async def test_the_pcap_is_also_served_raw(stack: ViewStack) -> None:
    put_file(stack, "dump.pcap", b"pcap-bytes")

    response = await stack.client.get(f"/api/analyses/{stack.analysis_id}/pcap")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/vnd.tcpdump.pcap"
    assert response.content == b"pcap-bytes"
    assert re.search(r'filename="analysis-\d+\.pcap"', response.headers["content-disposition"])


async def test_a_missing_pcap_is_a_404(stack: ViewStack) -> None:
    response = await stack.client.get(f"/api/analyses/{stack.analysis_id}/pcap")

    assert response.status_code == 404


async def test_a_screenshot_is_served_as_its_image(stack: ViewStack) -> None:
    put_file(stack, "shots/0001.jpg", b"jpeg-one")
    put_file(stack, "shots/0002.png", b"png-two")

    first = await stack.client.get(f"/api/analyses/{stack.analysis_id}/artifacts/screenshots/1")
    second = await stack.client.get(f"/api/analyses/{stack.analysis_id}/artifacts/screenshots/2")

    assert (first.status_code, first.headers["content-type"], first.content) == (
        200,
        "image/jpeg",
        b"jpeg-one",
    )
    assert (second.headers["content-type"], second.content) == ("image/png", b"png-two")


@pytest.mark.parametrize("n", ["0", "3", "-1", "999"])
async def test_a_screenshot_out_of_range_is_a_404(stack: ViewStack, n: str) -> None:
    put_file(stack, "shots/0001.jpg", b"jpeg-one")
    put_file(stack, "shots/0002.jpg", b"jpeg-two")

    response = await stack.client.get(
        f"/api/analyses/{stack.analysis_id}/artifacts/screenshots/{n}"
    )

    assert response.status_code == 404


async def test_a_screenshot_path_cannot_name_a_file(stack: ViewStack) -> None:
    put_file(stack, "shots/0001.jpg", b"jpeg-one")

    response = await stack.client.get(
        f"/api/analyses/{stack.analysis_id}/artifacts/screenshots/..%2F..%2Fdump.pcap"
    )

    assert response.status_code in (404, 422)
    assert b"jpeg-one" not in response.content
