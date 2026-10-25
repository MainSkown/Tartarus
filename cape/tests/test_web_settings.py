"""CAPE's Django web process serves the REST API to the backend and nothing else (C2 F4).

Django is not installed beside these tests, so the two Tartarus files are run against stand-ins for
CAPE's `web.settings` and for `django.urls`/`apiv2`.
"""

import importlib.util
import sys
import types
from pathlib import Path

import pytest

CAPE = Path(__file__).resolve().parents[1]
WEB = CAPE / "web"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path, submodule_search_locations=None)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def web_package(monkeypatch):
    package = types.ModuleType("web")
    package.__path__ = []  # type: ignore[attr-defined]
    settings = types.ModuleType("web.settings")
    settings.DEBUG = True  # type: ignore[attr-defined]
    settings.ALLOWED_HOSTS = ["*"]  # type: ignore[attr-defined]
    settings.ROOT_URLCONF = "web.urls"  # type: ignore[attr-defined]
    for name, module in (("web", package), ("web.settings", settings)):
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setenv("CAPE_INTERNAL_IP", "172.19.0.2")
    yield
    sys.modules.pop("web.local_settings", None)


def test_debug_is_off(web_package):
    assert load("web.local_settings", WEB / "local_settings.py").DEBUG is False


def test_only_the_names_the_backend_and_the_healthcheck_use_are_allowed_hosts(web_package):
    hosts = load("web.local_settings", WEB / "local_settings.py").ALLOWED_HOSTS

    assert "*" not in hosts
    assert {"cape", "cape-internal", "127.0.0.1", "172.19.0.2"} <= set(hosts)


def test_a_missing_internal_address_adds_no_empty_host(web_package, monkeypatch):
    monkeypatch.delenv("CAPE_INTERNAL_IP")

    assert "" not in load("web.local_settings", WEB / "local_settings.py").ALLOWED_HOSTS


def test_the_session_database_is_where_cape_may_write(web_package):
    database = load("web.local_settings", WEB / "local_settings.py").DATABASES["default"]

    assert database["NAME"] == "/var/lib/cape-web/siteauth.sqlite"


def test_the_root_urlconf_is_the_tartarus_one(web_package):
    assert load("web.local_settings", WEB / "local_settings.py").ROOT_URLCONF == "web.tartarus_urls"


def test_the_tartarus_urlconf_routes_apiv2_and_nothing_else(monkeypatch):
    routes: list[tuple[str, object]] = []
    django = types.ModuleType("django")
    urls = types.ModuleType("django.urls")
    urls.re_path = lambda pattern, view: routes.append((pattern, view)) or (pattern, view)  # type: ignore[attr-defined]
    urls.include = lambda module: ("include", module)  # type: ignore[attr-defined]
    apiv2 = types.ModuleType("apiv2")
    apiv2_urls = types.ModuleType("apiv2.urls")
    apiv2.urls = apiv2_urls  # type: ignore[attr-defined]
    for name, module in (
        ("django", django),
        ("django.urls", urls),
        ("apiv2", apiv2),
        ("apiv2.urls", apiv2_urls),
    ):
        monkeypatch.setitem(sys.modules, name, module)

    module = load("tartarus_urls_under_test", WEB / "tartarus_urls.py")

    assert [pattern for pattern, _ in routes] == [r"^apiv2/"]
    assert module.urlpatterns == [(r"^apiv2/", ("include", apiv2_urls))]
