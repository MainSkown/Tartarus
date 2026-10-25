import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
COMPOSE_FILES = (REPO / "docker-compose.yml", REPO / "docker-compose.dev.yml")
PINNED = re.compile(r"^[^\s@$]+:[^\s@$]+@sha256:[0-9a-f]{64}$")
FROM_LINE = re.compile(r"^\s*FROM\s+(?:--\S+\s+)*(\S+)(?:\s+AS\s+(\S+))?\s*$", re.IGNORECASE)
COPY_FROM_LINE = re.compile(r"^\s*COPY\s+.*?--from=(\S+)", re.IGNORECASE)
COMPOSE_MERGE_TAG = re.compile(r"!\w+")
SKIPPED_DIRS = {".git", ".venv", "node_modules", "__pycache__"}


def base_images(dockerfile_text: str) -> list[str]:
    stages: set[str] = set()
    images: list[str] = []
    for line in dockerfile_text.splitlines():
        if match := FROM_LINE.match(line):
            image, stage = match.groups()
            if image.lower() != "scratch" and image.lower() not in stages:
                images.append(image)
            if stage:
                stages.add(stage.lower())
        elif match := COPY_FROM_LINE.match(line):
            source = match.group(1)
            if source.lower() not in stages:
                images.append(source)
    return images


def pulled_images(compose_text: str) -> dict[str, str]:
    # Compose merge tags (`ports: !override`) are not YAML types; dropping them leaves the value.
    services = yaml.safe_load(COMPOSE_MERGE_TAG.sub("", compose_text))["services"]
    return {
        name: str(service["image"])
        for name, service in services.items()
        if "image" in service and "build" not in service
    }


def dockerfiles() -> list[Path]:
    return sorted(
        path
        for path in REPO.rglob("Dockerfile*")
        if path.is_file() and not SKIPPED_DIRS.intersection(path.relative_to(REPO).parts)
    )


def unpinned(images: list[str]) -> list[str]:
    return [image for image in images if not PINNED.match(image)]


def test_base_images_skip_scratch_and_earlier_stage_names() -> None:
    text = "FROM scratch AS empty\nFROM ubuntu:24.04 AS build\n"
    text += "FROM build AS dev\nFROM node:24 AS web\n"
    assert base_images(text) == ["ubuntu:24.04", "node:24"]


def test_copy_from_an_external_image_is_a_base_image() -> None:
    text = "FROM python:3.12-slim AS base\nCOPY --from=ghcr.io/astral-sh/uv:0.12 /uv /bin/\n"
    text += "COPY --from=base /x /y\n"
    assert base_images(text) == ["python:3.12-slim", "ghcr.io/astral-sh/uv:0.12"]


def test_base_images_accept_platform_flags_and_lowercase_keywords() -> None:
    text = "from --platform=linux/amd64 python:3.12-slim as base\n"
    assert base_images(text) == ["python:3.12-slim"]


def test_pinned_reference_needs_a_full_sha256_digest() -> None:
    assert PINNED.match("postgres:16@sha256:" + "a" * 64)
    assert not PINNED.match("postgres:16@sha256:" + "a" * 63)
    assert not PINNED.match("postgres:16")
    assert not PINNED.match("postgres@sha256:" + "a" * 64 + "x")


def test_compose_merge_tags_do_not_hide_the_images() -> None:
    text = "services:\n  db:\n    image: postgres:16\n  web:\n    build: .\n"
    text += "    ports: !override\n      - '1:1'\n"
    assert pulled_images(text) == {"db": "postgres:16"}


def test_every_dockerfile_base_image_is_pinned() -> None:
    images = {
        path.relative_to(REPO).as_posix(): base_images(path.read_text()) for path in dockerfiles()
    }
    assert images, "no Dockerfiles found"
    assert all(images.values()), "a Dockerfile has no base image"
    problems = {path: unpinned(found) for path, found in images.items() if unpinned(found)}
    assert problems == {}


def test_every_pulled_compose_image_is_pinned() -> None:
    problems = {}
    for path in COMPOSE_FILES:
        found = {
            name: image
            for name, image in pulled_images(path.read_text()).items()
            if not PINNED.match(image)
        }
        if found:
            problems[path.name] = found
    assert problems == {}
