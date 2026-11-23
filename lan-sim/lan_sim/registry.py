"""The services the daemon can serve, by kind, collected from `lan_sim.services.<kind>`."""

import importlib
from collections.abc import Iterable

from lan_sim.service import Service

SERVICE_KINDS = ("smb", "rdp", "winrm", "ssh", "ldap", "mssql")


def build_registry(kinds: Iterable[str] = SERVICE_KINDS) -> dict[str, Service]:
    """Each kind's module exposes its protocol as `SERVICE`; a kind without a module is skipped."""
    registry: dict[str, Service] = {}
    for kind in kinds:
        service = _service_of(kind)
        if service is not None:
            registry[kind] = service
    return registry


def _service_of(kind: str) -> Service | None:
    module_name = f"lan_sim.services.{kind}"
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as error:
        # Only the service's own module may be missing; a failing import inside it is a bug.
        if error.name == module_name:
            return None
        raise
    service: Service = module.SERVICE
    if service.kind != kind:
        raise ValueError(f"{module_name}.SERVICE has kind {service.kind!r}, not {kind!r}")
    return service
