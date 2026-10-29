import logging
import tempfile
from pathlib import Path

import httpx
import pytest
from fastapi import Request

from app.api.dependencies import get_sample_store
from app.api.upload_limit import MULTIPART_ALLOWANCE
from app.db.models import Analysis, Sample
from app.samples.store import SampleStore
from tests import test_analyses_api
from tests.test_analyses_api import Harness
from tests.test_archive_members import PASSWORD, ZIPCRYPTO_FIXTURE, write_aes_zip, write_plain_zip

# pytest finds a fixture by its name in the test module, so the shared harness is bound here.
harness = test_analyses_api.harness

ENDPOINT = "/api/analyses/archive-members"
SECRET = "hunter2-top-secret"  # noqa: S105
MEMBER_LIMIT_MESSAGE = "the zip contains more than 1000 files"
NOT_A_ZIP_MESSAGE = "the file is not a valid zip archive"
ZIPCRYPTO_BYTES = ZIPCRYPTO_FIXTURE.read_bytes()


def leftovers(directory: Path) -> list[Path]:
    return list(directory.iterdir())


def aes_zip(tmp_path: Path, members: dict[str, bytes], password: str = PASSWORD) -> bytes:
    return write_aes_zip(tmp_path / "built.zip", members, password).read_bytes()


def plain_zip(tmp_path: Path, members: dict[str, bytes]) -> bytes:
    return write_plain_zip(tmp_path / "built.zip", members).read_bytes()


async def upload_archive(
    client: httpx.AsyncClient, content: bytes, password: str | None = None
) -> httpx.Response:
    data = {} if password is None else {"password": password}
    return await client.post(ENDPOINT, files={"file": ("sample.zip", content)}, data=data)


def rejection_fields(response: httpx.Response) -> list[dict[str, object]]:
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    return response.json()["error"]["details"]["fields"]


@pytest.fixture
def scratch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "scratch"
    directory.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(directory))
    return directory


async def test_members_of_an_aes_zip_are_listed_and_the_password_is_accepted(
    harness: Harness, tmp_path: Path
) -> None:
    content = aes_zip(tmp_path, {"loader.exe": b"MZ" * 10, "config/settings.ini": b"x"})

    response = await upload_archive(harness.client, content, PASSWORD)

    assert response.status_code == 200
    assert response.json() == {
        "members": [
            {
                "name": "loader.exe",
                "size": 20,
                "encrypted": True,
                "unsafe": False,
                "unsupported": False,
            },
            {
                "name": "config/settings.ini",
                "size": 1,
                "encrypted": True,
                "unsafe": False,
                "unsupported": False,
            },
        ],
        "password_ok": True,
    }


async def test_the_password_defaults_to_infected(harness: Harness, tmp_path: Path) -> None:
    content = aes_zip(tmp_path, {"loader.exe": b"MZ"})

    response = await upload_archive(harness.client, content)

    assert response.json()["password_ok"] is True


async def test_a_wrong_password_is_reported_and_the_members_are_still_listed(
    harness: Harness, tmp_path: Path
) -> None:
    content = aes_zip(tmp_path, {"loader.exe": b"MZ"})

    response = await upload_archive(harness.client, content, "not-the-password")

    assert response.status_code == 200
    assert response.json()["password_ok"] is False
    assert [member["name"] for member in response.json()["members"]] == ["loader.exe"]


async def test_a_zipcrypto_archive_is_listed_and_the_password_accepted(harness: Harness) -> None:
    response = await upload_archive(harness.client, ZIPCRYPTO_BYTES, PASSWORD)

    assert response.status_code == 200
    assert response.json() == {
        "members": [
            {
                "name": "hello.txt",
                "size": 15,
                "encrypted": True,
                "unsafe": False,
                "unsupported": False,
            }
        ],
        "password_ok": True,
    }


async def test_an_archive_without_encrypted_members_has_no_password_verdict(
    harness: Harness, tmp_path: Path
) -> None:
    content = plain_zip(tmp_path, {"loader.exe": b"MZ"})

    response = await upload_archive(harness.client, content)

    assert response.json() == {
        "members": [
            {
                "name": "loader.exe",
                "size": 2,
                "encrypted": False,
                "unsafe": False,
                "unsupported": False,
            }
        ],
        "password_ok": None,
    }


async def test_a_member_that_escapes_the_directory_is_listed_as_unsafe(
    harness: Harness, tmp_path: Path
) -> None:
    content = plain_zip(tmp_path, {"../evil.exe": b"MZ"})

    response = await upload_archive(harness.client, content)

    assert response.status_code == 200
    (member,) = response.json()["members"]
    assert (member["name"], member["unsafe"]) == ("../evil.exe", True)


async def test_a_member_whose_name_the_option_string_cannot_carry_is_unsupported(
    harness: Harness, tmp_path: Path
) -> None:
    content = plain_zip(tmp_path, {"a,b.exe": b"MZ"})

    response = await upload_archive(harness.client, content)

    (member,) = response.json()["members"]
    assert (member["name"], member["unsupported"]) == ("a,b.exe", True)


async def test_data_that_is_not_a_zip_is_a_422_naming_the_file(harness: Harness) -> None:
    response = await upload_archive(harness.client, b"this is not a zip file" * 10)

    assert rejection_fields(response) == [
        {"location": ["body", "file"], "message": NOT_A_ZIP_MESSAGE, "type": "value_error.archive"}
    ]


async def test_an_empty_file_is_a_422_naming_the_file(harness: Harness) -> None:
    response = await upload_archive(harness.client, b"")

    assert rejection_fields(response) == [
        {
            "location": ["body", "file"],
            "message": "The uploaded file is empty",
            "type": "value_error.empty",
        }
    ]


async def test_more_members_than_the_cap_is_a_422(harness: Harness, tmp_path: Path) -> None:
    content = plain_zip(tmp_path, {f"f{number}.bin": b"x" for number in range(1001)})

    response = await upload_archive(harness.client, content)

    assert rejection_fields(response) == [
        {
            "location": ["body", "file"],
            "message": MEMBER_LIMIT_MESSAGE,
            "type": "value_error.archive",
        }
    ]


async def test_a_password_longer_than_256_characters_is_a_422_naming_the_field(
    harness: Harness, tmp_path: Path
) -> None:
    content = aes_zip(tmp_path, {"loader.exe": b"MZ"})

    response = await upload_archive(harness.client, content, "p" * 257)

    assert [field["location"] for field in rejection_fields(response)] == [["body", "password"]]


async def test_an_archive_over_the_size_limit_is_a_413_and_its_copy_is_removed(
    harness: Harness, tmp_path: Path, scratch: Path
) -> None:
    harness.app.dependency_overrides[get_sample_store] = lambda: SampleStore(
        harness.store.root, max_bytes=8
    )

    response = await upload_archive(harness.client, aes_zip(tmp_path, {"loader.exe": b"MZ"}))

    assert response.status_code == 413
    assert response.json()["error"]["message"] == "The file is larger than 8 bytes"
    assert leftovers(scratch) == []


async def test_a_body_announced_far_over_the_limit_is_refused_before_it_is_parsed(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness.app.dependency_overrides[get_sample_store] = lambda: SampleStore(
        harness.store.root, max_bytes=8
    )

    async def never_parsed(self: Request) -> None:
        raise AssertionError("the multipart body was parsed")

    monkeypatch.setattr(Request, "_get_form", never_parsed)

    response = await upload_archive(harness.client, b"x" * (2 * MULTIPART_ALLOWANCE))

    assert response.status_code == 413


async def test_the_copy_is_removed_after_a_valid_archive(
    harness: Harness, tmp_path: Path, scratch: Path
) -> None:
    response = await upload_archive(harness.client, aes_zip(tmp_path, {"loader.exe": b"MZ"}))

    assert response.status_code == 200
    assert leftovers(scratch) == []


async def test_the_copy_is_removed_after_a_rejected_archive(
    harness: Harness, scratch: Path
) -> None:
    response = await upload_archive(harness.client, b"not a zip" * 20)

    assert response.status_code == 422
    assert leftovers(scratch) == []


async def test_the_password_is_in_neither_the_responses_nor_the_log(
    harness: Harness, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    content = aes_zip(tmp_path, {"loader.exe": b"MZ"}, SECRET)

    with caplog.at_level(logging.DEBUG):
        accepted = await upload_archive(harness.client, content, SECRET)
        mistaken = await upload_archive(harness.client, content, SECRET + "-wrong")
        refused = await upload_archive(harness.client, b"not a zip" * 20, SECRET)
        too_long = await upload_archive(harness.client, content, SECRET + "x" * 300)

    assert accepted.json()["password_ok"] is True
    assert mistaken.json()["password_ok"] is False
    for response in (accepted, mistaken, refused, too_long):
        assert SECRET not in response.text
    assert SECRET not in caplog.text


async def test_nothing_is_stored_or_queued(harness: Harness, tmp_path: Path) -> None:
    response = await upload_archive(harness.client, aes_zip(tmp_path, {"loader.exe": b"MZ"}))

    assert response.status_code == 200
    assert await harness.rows(Sample) == []
    assert await harness.rows(Analysis) == []
    assert harness.stored_files() == []
    assert harness.runner.nudges == 0


async def test_the_operation_is_named_analyses_archive_members(harness: Harness) -> None:
    operation = harness.app.openapi()["paths"][ENDPOINT]["post"]

    assert operation["operationId"] == "analyses_archive_members"


async def test_the_operation_description_lists_the_refusals(harness: Harness) -> None:
    description = harness.app.openapi()["paths"][ENDPOINT]["post"]["description"]

    assert "`413`" in description
    assert "`422`" in description
