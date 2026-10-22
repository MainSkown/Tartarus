import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
NGINX_CONF = (REPO / "frontend" / "nginx.conf").read_text()

SECURITY_HEADERS = ("X-Content-Type-Options", "Referrer-Policy", "X-Frame-Options")


def _server_block() -> str:
    match = re.search(r"\nserver\s*\{(.*)\n\}", NGINX_CONF, re.S)
    assert match
    return match.group(1)


def _locations() -> list[str]:
    return re.findall(r"\n    location[^{]*\{(.*?)\n    \}", _server_block(), re.S)


def _server_level_text() -> str:
    return re.sub(r"\n    location[^{]*\{.*?\n    \}", "", _server_block(), flags=re.S)


def _csp() -> dict[str, str]:
    match = re.search(r'add_header Content-Security-Policy "([^"]+)" always;', NGINX_CONF)
    assert match, "no Content-Security-Policy header"
    directives = [part.split(maxsplit=1) for part in match.group(1).split(";") if part.strip()]
    return {name: "".join(value) for name, *value in directives}


def test_nginx_does_not_advertise_its_version() -> None:
    assert "server_tokens off;" in NGINX_CONF


def test_every_response_carries_the_security_headers() -> None:
    server_level = _server_level_text()
    for header in SECURITY_HEADERS:
        assert re.search(rf"add_header {header} \S+.* always;", server_level), header


def test_no_location_sets_its_own_headers_because_that_would_drop_the_inherited_ones() -> None:
    assert not [block for block in _locations() if "add_header" in block]


def test_the_content_security_policy_forbids_framing_plugins_and_foreign_sources() -> None:
    policy = _csp()

    assert policy["default-src"] == "'self'"
    assert policy["script-src"] == "'self'"
    assert policy["frame-ancestors"] == "'none'"
    assert policy["object-src"] == "'none'"
    assert policy["connect-src"] == "'self'"


def test_the_content_security_policy_allows_the_canvas_and_blob_images_guacamole_draws_with() -> (
    None
):
    assert {"'self'", "data:", "blob:"} <= set(_csp()["img-src"].split())


def test_a_foreign_host_is_answered_421_for_the_whole_server() -> None:
    assert re.search(r"if \(\$host_allowed = 0\)\s*\{\s*return 421;", _server_level_text())


def test_a_foreign_origin_on_a_websocket_or_an_unsafe_api_request_is_answered_403() -> None:
    assert re.search(r"if \(\$refuse_origin\)\s*\{\s*return 403;", _server_level_text())
    assert "location /ws/" in NGINX_CONF
    refusal_rules = re.search(r"map [^{]*\$refuse_origin\s*\{(.*?)\n\}", NGINX_CONF, re.S)
    assert refusal_rules
    assert "/ws/" in refusal_rules.group(1)
    assert "/api/" in refusal_rules.group(1)
