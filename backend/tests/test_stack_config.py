import configparser
import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
CUCKOO_CONF = REPO / "cape" / "conf" / "cuckoo.conf"
WEB_CONF = REPO / "cape" / "conf" / "web.conf"
NGINX_CONF = REPO / "frontend" / "nginx.conf"
COMPOSE_FILE = REPO / "docker-compose.yml"

MEMORY_IMAGE_UPLOAD_PATH = "/api/analyses/import/memory-image"
PCAP_UPLOAD_LIMIT_BYTES = 536870912
MEMORY_IMAGE_UPLOAD_LIMIT = "5g"
IMPORTS_VOLUME_MOUNT = "imports:/imports"


def _conf(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(path)
    return parser


def _nginx_location(path_expression: str) -> str:
    text = NGINX_CONF.read_text()
    match = re.search(rf"location\s+{re.escape(path_expression)}\s*\{{(.*?)\n    \}}", text, re.S)
    assert match, f"no nginx location {path_expression!r}"
    return match.group(1)


def _compose() -> dict[str, object]:
    return yaml.safe_load(COMPOSE_FILE.read_text())


def test_cape_does_not_resolve_pcap_domains_live() -> None:
    assert _conf(CUCKOO_CONF).get("processing", "resolve_dns") == "off"


def test_cape_accepts_pcap_uploads_up_to_the_product_limit() -> None:
    assert _conf(WEB_CONF).getint("general", "max_sample_size") == PCAP_UPLOAD_LIMIT_BYTES


def test_memory_image_upload_location_takes_five_gigabytes_unbuffered() -> None:
    block = _nginx_location(f"= {MEMORY_IMAGE_UPLOAD_PATH}")
    assert f"client_max_body_size {MEMORY_IMAGE_UPLOAD_LIMIT};" in block
    assert "proxy_request_buffering off;" in block
    assert "proxy_pass $backend;" in block


def test_api_location_keeps_the_512_megabyte_limit() -> None:
    assert "client_max_body_size 512m;" in _nginx_location("/api/")


def test_backend_writes_imports_and_cape_reads_them_read_only() -> None:
    services = _compose()["services"]
    assert IMPORTS_VOLUME_MOUNT in services["backend"]["volumes"]
    assert f"{IMPORTS_VOLUME_MOUNT}:ro" in services["cape"]["volumes"]


def test_imports_volume_is_declared() -> None:
    assert "imports" in (_compose()["volumes"] or {})
