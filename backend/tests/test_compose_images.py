import pytest

from tests.compose_images import compose_image


def test_reads_store_images_from_the_compose_file() -> None:
    assert compose_image("postgres").startswith("postgres:")
    assert compose_image("opensearch").startswith("opensearchproject/opensearch:")


def test_unknown_service_raises() -> None:
    with pytest.raises(KeyError):
        compose_image("no-such-service")
