import configparser
import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
CUCKOO_CONF = REPO / "cape" / "conf" / "cuckoo.conf"
WEB_CONF = REPO / "cape" / "conf" / "web.conf"
PROCESSING_CONF = REPO / "cape" / "conf" / "processing.conf"
REPORTING_CONF = REPO / "cape" / "conf" / "reporting.conf"
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


def test_backend_image_hands_the_imports_folder_to_its_user() -> None:
    # A named volume takes the owner of the image's folder on first use; without the folder the
    # volume is root's and the unprivileged backend cannot write an upload.
    dockerfile = (REPO / "backend" / "Dockerfile").read_text()
    assert re.search(r"mkdir -p[^\n]*\s/imports\b", dockerfile)
    assert re.search(r"chown tartarus:tartarus[^\n]*\s/imports\b", dockerfile)


# What libvirt, QEMU, the rooter and the ISO scan were measured to need (docs/security.md):
# anything more is a way out of the container, anything less stops a guest.
CAPE_CAPABILITIES = {
    "CHOWN",
    "DAC_OVERRIDE",
    "FOWNER",
    "KILL",
    "MKNOD",
    "NET_ADMIN",
    "NET_BIND_SERVICE",
    "NET_RAW",
    "SETGID",
    "SETPCAP",
    "SETUID",
    "SYS_ADMIN",
    "SYS_CHROOT",
    "SYS_PTRACE",
}
CAPE_DEVICES = {"/dev/kvm", "/dev/net/tun", "/dev/vhost-net", "/dev/loop-control"}
LOOP_DEVICES_RULE = "b 7:* rmw"


def _cape_service() -> dict[str, object]:
    return _compose()["services"]["cape"]


def test_no_service_is_privileged() -> None:
    services = _compose()["services"]

    assert not [name for name, service in services.items() if service.get("privileged")]


def test_cape_holds_exactly_the_capabilities_it_was_measured_to_need() -> None:
    cape = _cape_service()

    assert cape["cap_drop"] == ["ALL"]
    assert set(cape["cap_add"]) == CAPE_CAPABILITIES
    assert "security_opt" not in cape


def test_cape_sees_only_the_devices_a_guest_and_the_iso_scan_need() -> None:
    cape = _cape_service()

    assert {device.split(":")[0] for device in cape["devices"]} == CAPE_DEVICES
    assert cape["device_cgroup_rules"] == [LOOP_DEVICES_RULE]


def test_cape_sends_nothing_about_a_sample_to_a_third_party() -> None:
    # CAPE's defaults look every sample and URL up at VirusTotal and whois; the cape user has no
    # route out, so left on they would only fail on every task.
    processing = _conf(PROCESSING_CONF)

    assert processing.get("virustotal", "enabled") == "no"
    assert processing.get("url_analysis", "whois") == "no"


def test_cape_does_not_call_the_backend() -> None:
    # The cape user parses hostile output and may not open a connection to the backend's API; the
    # backend learns that a task finished by polling its status.
    assert _conf(REPORTING_CONF).get("callback", "enabled") == "no"
