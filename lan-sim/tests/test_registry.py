import sys
from types import ModuleType

import pytest

from lan_sim import services
from lan_sim.registry import SERVICE_KINDS, build_registry


class StubService:
    def __init__(self, kind: str) -> None:
        self.kind = kind

    async def serve(self, connection) -> None:
        raise NotImplementedError


def install(monkeypatch, kind: str, service: object) -> StubService | object:
    module = ModuleType(f"lan_sim.services.{kind}")
    module.SERVICE = service
    monkeypatch.setitem(sys.modules, module.__name__, module)
    return service


def test_the_kinds_are_the_six_protocols_a_preset_may_name():
    assert SERVICE_KINDS == ("smb", "rdp", "winrm", "ssh", "ldap", "mssql")


def test_a_module_that_exists_is_registered_under_its_kind(monkeypatch):
    smb = install(monkeypatch, "smb", StubService("smb"))
    registry = build_registry(("smb",))
    assert registry == {"smb": smb}


def test_every_module_that_exists_is_registered(monkeypatch):
    smb = install(monkeypatch, "smb", StubService("smb"))
    ssh = install(monkeypatch, "ssh", StubService("ssh"))
    assert build_registry(("smb", "ssh")) == {"smb": smb, "ssh": ssh}


def test_a_module_that_does_not_exist_yet_is_skipped(monkeypatch):
    smb = install(monkeypatch, "smb", StubService("smb"))
    monkeypatch.delitem(sys.modules, "lan_sim.services.nosuchprotocol", raising=False)
    assert build_registry(("smb", "nosuchprotocol")) == {"smb": smb}


def test_a_module_that_fails_to_import_a_dependency_still_raises(monkeypatch, tmp_path):
    (tmp_path / "broken.py").write_text("import a_dependency_that_is_not_installed\n")
    monkeypatch.setattr(services, "__path__", [*services.__path__, str(tmp_path)])
    monkeypatch.delitem(sys.modules, "lan_sim.services.broken", raising=False)
    with pytest.raises(ModuleNotFoundError) as caught:
        build_registry(("broken",))
    assert caught.value.name == "a_dependency_that_is_not_installed"


def test_a_module_that_imports_a_missing_sibling_service_still_raises(monkeypatch, tmp_path):
    (tmp_path / "needy.py").write_text("import lan_sim.services.nosuchprotocol\n")
    monkeypatch.setattr(services, "__path__", [*services.__path__, str(tmp_path)])
    monkeypatch.delitem(sys.modules, "lan_sim.services.needy", raising=False)
    with pytest.raises(ModuleNotFoundError) as caught:
        build_registry(("needy",))
    assert caught.value.name == "lan_sim.services.nosuchprotocol"


def test_a_module_without_a_service_object_is_an_error(monkeypatch):
    module = ModuleType("lan_sim.services.bare")
    monkeypatch.setitem(sys.modules, module.__name__, module)
    with pytest.raises(AttributeError, match="SERVICE"):
        build_registry(("bare",))


def test_a_service_whose_kind_differs_from_its_module_is_an_error(monkeypatch):
    install(monkeypatch, "smb", StubService("rdp"))
    with pytest.raises(ValueError, match="smb"):
        build_registry(("smb",))


def test_the_default_is_every_known_kind_and_only_those(monkeypatch):
    for kind in SERVICE_KINDS:
        install(monkeypatch, kind, StubService(kind))
    assert set(build_registry()) == set(SERVICE_KINDS)
