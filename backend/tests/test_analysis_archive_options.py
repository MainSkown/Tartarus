import logging
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from app.analyses.archive_check import ArchiveRefusedError, require_runnable_archive
from app.db.models import Analysis, Sample
from app.samples.store import BytesSource, SampleStore
from app.schemas.analysis_requests import AnalysisOptions
from tests import test_analyses_api
from tests.analyses.helpers import app_log_text
from tests.test_analyses_api import Harness, error_locations
from tests.test_archive_members import ZIPCRYPTO_FIXTURE, write_aes_zip, write_plain_zip

# pytest finds a fixture by its name in the test module, so the shared harness is bound here.
harness = test_analyses_api.harness

PASSWORD = "s3cret-Pass"  # noqa: S105
WRONG_PASSWORD = "not-the-one"  # noqa: S105
ENTRY = "payload.exe"
ARCHIVE_OPTIONS = {"archive_password": PASSWORD, "archive_entry": ENTRY}
ARCHIVE_NAME = "sample.zip"


def archive_bytes(tmp_path: Path, members: dict[str, bytes] | None = None) -> bytes:
    built = write_aes_zip(tmp_path / "built.zip", members or {ENTRY: b"MZ" * 8}, PASSWORD)
    return built.read_bytes()


def messages(error: ValidationError) -> str:
    # `str(error)` holds the rejected input by design; the API path drops it (`parse_options`).
    return " | ".join(str(each["msg"]) for each in error.errors(include_input=False))


async def submit_archive(harness: Harness, content: bytes, **options: Any) -> httpx.Response:
    return await harness.upload(content, ARCHIVE_NAME, {**ARCHIVE_OPTIONS, **options})


def refusal(response: httpx.Response) -> dict[str, Any]:
    assert response.status_code == 422
    (field,) = response.json()["error"]["details"]["fields"]
    assert PASSWORD not in response.text
    return field  # type: ignore[no-any-return]


async def assert_nothing_was_kept(harness: Harness) -> None:
    assert await harness.rows(Sample) == []
    assert await harness.rows(Analysis) == []
    assert harness.stored_files() == []
    assert harness.runner.nudges == 0


def test_the_archive_fields_are_optional() -> None:
    options = AnalysisOptions()

    assert (options.archive_password, options.archive_entry) == (None, None)
    assert options.package == "auto"


def test_a_password_and_an_entry_are_accepted_together_and_force_the_zip_package() -> None:
    options = AnalysisOptions(archive_password=PASSWORD, archive_entry="dir/a b.exe")

    assert (options.archive_password, options.archive_entry) == (PASSWORD, "dir/a b.exe")
    assert options.package == "zip"


def test_the_zip_package_is_accepted_with_the_archive_fields() -> None:
    options = AnalysisOptions(package="zip", **ARCHIVE_OPTIONS)

    assert options.package == "zip"


@pytest.mark.parametrize("package", ["exe", "dll", "doc"])
def test_another_package_is_refused_with_the_archive_fields(package: str) -> None:
    with pytest.raises(ValidationError) as refused:
        AnalysisOptions(package=package, **ARCHIVE_OPTIONS)

    assert "package" in messages(refused.value)
    assert PASSWORD not in messages(refused.value)


@pytest.mark.parametrize("only", [{"archive_password": PASSWORD}, {"archive_entry": ENTRY}])
def test_one_archive_field_without_the_other_is_refused(only: dict[str, str]) -> None:
    with pytest.raises(ValidationError) as refused:
        AnalysisOptions(**only)

    assert "together" in messages(refused.value)
    assert PASSWORD not in messages(refused.value)


@pytest.mark.parametrize(
    "password",
    [
        "",
        "a" * 257,
        "pass,word",
        " leading",
        "trailing ",
        "\tpass",
        "with\nnewline",
        "with\x00nul",
        "with\x7fdel",
    ],
)
def test_a_password_cape_cannot_carry_is_refused_without_repeating_it(password: str) -> None:
    with pytest.raises(ValidationError) as refused:
        AnalysisOptions(archive_password=password, archive_entry=ENTRY)

    assert "archive_password" in messages(refused.value)
    assert not password or password not in messages(refused.value)


@pytest.mark.parametrize(
    "entry",
    ["", "a" * 513, "dir/a,b.exe", " lead.exe", "trail.exe ", "x\ny.exe", "x\x00.exe"],
)
def test_an_entry_cape_cannot_carry_is_refused(entry: str) -> None:
    with pytest.raises(ValidationError) as refused:
        AnalysisOptions(archive_password=PASSWORD, archive_entry=entry)

    assert "archive_entry" in messages(refused.value)
    assert PASSWORD not in messages(refused.value)


def test_the_longest_password_and_entry_are_accepted() -> None:
    options = AnalysisOptions(archive_password="p" * 256, archive_entry="e" * 512)

    assert len(options.archive_password or "") == 256
    assert len(options.archive_entry or "") == 512


def test_an_unknown_option_is_still_refused() -> None:
    with pytest.raises(ValidationError):
        AnalysisOptions.model_validate({**ARCHIVE_OPTIONS, "archive_comment": "x"})


async def test_an_invalid_password_is_a_422_that_never_repeats_it(harness: Harness) -> None:
    bad = f"{PASSWORD},with-a-comma"

    response = await harness.upload(
        b"PK", ARCHIVE_NAME, {"archive_password": bad, "archive_entry": ENTRY}
    )

    assert response.status_code == 422
    assert bad not in response.text
    assert PASSWORD not in response.text
    assert ["body", "options", "archive_password"] in error_locations(response)
    await assert_nothing_was_kept(harness)


async def test_an_archive_submission_keeps_both_fields_and_the_zip_package(
    harness: Harness, tmp_path: Path
) -> None:
    response = await submit_archive(harness, archive_bytes(tmp_path))

    assert response.status_code == 201
    stored = (await harness.rows(Analysis))[0]
    assert stored.options["package"] == "zip"
    assert stored.options["archive_password"] == PASSWORD
    assert stored.options["archive_entry"] == ENTRY
    assert stored.filename == ARCHIVE_NAME
    assert harness.runner.nudges == 1


async def test_the_package_auto_is_stored_as_zip_for_an_archive(
    harness: Harness, tmp_path: Path
) -> None:
    response = await submit_archive(harness, archive_bytes(tmp_path), package="auto")

    assert response.json()["options"]["package"] == "zip"


async def test_a_zipcrypto_archive_is_accepted(harness: Harness) -> None:
    response = await harness.upload(
        ZIPCRYPTO_FIXTURE.read_bytes(),
        ARCHIVE_NAME,
        {"archive_password": "infected", "archive_entry": "hello.txt"},
    )

    assert response.status_code == 201


async def test_an_archive_without_encrypted_members_is_accepted_whatever_the_password(
    harness: Harness, tmp_path: Path
) -> None:
    plain = write_plain_zip(tmp_path / "plain.zip", {ENTRY: b"MZ"}).read_bytes()

    assert (await submit_archive(harness, plain)).status_code == 201


async def test_a_wrong_password_is_a_422_and_nothing_is_kept(
    harness: Harness, tmp_path: Path
) -> None:
    response = await submit_archive(
        harness, archive_bytes(tmp_path), archive_password=WRONG_PASSWORD
    )

    field = refusal(response)
    assert field["location"] == ["body", "options", "archive_password"]
    assert "password" in field["message"]
    assert WRONG_PASSWORD not in response.text
    await assert_nothing_was_kept(harness)


async def test_an_entry_that_is_not_in_the_archive_is_a_422_naming_it(
    harness: Harness, tmp_path: Path
) -> None:
    response = await submit_archive(harness, archive_bytes(tmp_path), archive_entry="other.exe")

    field = refusal(response)
    assert field["location"] == ["body", "options", "archive_entry"]
    assert "other.exe" in field["message"]
    await assert_nothing_was_kept(harness)


async def test_an_unsafe_member_cannot_be_the_entry(harness: Harness, tmp_path: Path) -> None:
    content = archive_bytes(tmp_path, {ENTRY: b"MZ", "../evil": b"MZ"})

    response = await submit_archive(harness, content, archive_entry="../evil")

    field = refusal(response)
    assert field["location"] == ["body", "options", "archive_entry"]
    assert "unsafe" in field["message"]
    await assert_nothing_was_kept(harness)


async def test_a_member_name_with_a_comma_cannot_be_the_entry(
    harness: Harness, tmp_path: Path
) -> None:
    content = archive_bytes(tmp_path, {ENTRY: b"MZ", "a,b.exe": b"MZ"})

    response = await submit_archive(harness, content, archive_entry="a,b.exe")

    assert refusal(response)["location"] == ["body", "options", "archive_entry"]
    await assert_nothing_was_kept(harness)


@pytest.mark.parametrize(
    ("member", "reason"), [("a,b.exe", "comma"), ("../evil", "unsafe"), ("gone.exe", "not a file")]
)
async def test_the_archive_check_refuses_a_member_that_cannot_be_chosen(
    tmp_path: Path, member: str, reason: str
) -> None:
    store = SampleStore(tmp_path / "samples")
    zip_path = write_aes_zip(
        tmp_path / "built.zip", {ENTRY: b"MZ", "a,b.exe": b"x", "../evil": b"x"}, PASSWORD
    )
    stored = await store.save(BytesSource(zip_path.read_bytes()), ARCHIVE_NAME)

    with pytest.raises(ArchiveRefusedError) as refused:
        await require_runnable_archive(store, stored.sha256, PASSWORD, member)

    assert refused.value.field == "options.archive_entry"
    assert reason in str(refused.value)


async def test_archive_fields_on_a_file_that_is_not_a_zip_are_a_422(harness: Harness) -> None:
    response = await harness.upload(b"MZ not a zip", "benign.exe", ARCHIVE_OPTIONS)

    field = refusal(response)
    assert field["location"] == ["body", "file"]
    assert "zip" in field["message"]
    await assert_nothing_was_kept(harness)


async def test_a_refused_archive_keeps_the_sample_another_analysis_uses(
    harness: Harness, tmp_path: Path
) -> None:
    content = archive_bytes(tmp_path)
    assert (await submit_archive(harness, content)).status_code == 201

    refused = await submit_archive(harness, content, archive_entry="other.exe")

    assert refused.status_code == 422
    assert len(await harness.rows(Sample)) == 1
    assert len(harness.stored_files()) == 1


async def test_a_submission_without_archive_fields_is_unchanged(harness: Harness) -> None:
    response = await harness.upload()

    assert response.status_code == 201
    assert "archive_entry" not in response.json()["options"]
    assert "archive_password" not in (await harness.rows(Analysis))[0].options


async def test_the_password_is_in_no_response_and_no_log(
    harness: Harness, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        created = await submit_archive(harness, archive_bytes(tmp_path))
        analysis_id = created.json()["id"]
        bodies = [
            created,
            await harness.client.get(f"/api/analyses/{analysis_id}"),
            await harness.client.get("/api/analyses"),
            await harness.client.post(f"/api/analyses/{analysis_id}/cancel"),
            await submit_archive(harness, archive_bytes(tmp_path), archive_password=WRONG_PASSWORD),
            await harness.upload(b"MZ", "benign.exe", ARCHIVE_OPTIONS),
        ]

    assert created.status_code == 201
    for response in bodies:
        assert PASSWORD not in response.text
    assert PASSWORD not in app_log_text(caplog)
    assert created.json()["options"]["archive_entry"] == ENTRY
    assert "archive_password" not in created.json()["options"]
    assert (await harness.rows(Analysis))[0].options["archive_password"] == PASSWORD
