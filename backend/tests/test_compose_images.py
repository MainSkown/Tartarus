import pytest

from tests.compose_images import compose_image


def test_reads_store_images_from_the_compose_file() -> None:
    assert compose_image("postgres").startswith("postgres:")
    assert compose_image("opensearch").startswith("opensearchproject/opensearch:")


def test_store_images_are_pinned_by_digest() -> None:
    assert "@sha256:" in compose_image("postgres")
    assert "@sha256:" in compose_image("opensearch")


def test_unknown_service_raises() -> None:
    with pytest.raises(KeyError):
        compose_image("no-such-service")
