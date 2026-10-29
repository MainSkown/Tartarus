"""Maps one Sysmon event's `EventData` onto the field catalog.

One function per event id, registered in `MAPPERS`. Which events are kept is `sysmon_noise`'s
business; which process acted is `sysmon_processes`'s. Event ids and fields:
https://learn.microsoft.com/sysinternals/downloads/sysmon
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.ingest.ecs import (
    EventShape,
    base_name,
    file_fields,
    registry_fields,
)
from app.ingest.sysmon_processes import (
    PROCESS_ACCESS,
    REMOTE_THREAD,
    EventFields,
    Subject,
    sha256_of,
    subject_of,
)

DATASET = "sysmon.evtx"
SERVICE_EVENTS = frozenset({4, 16})  # Sysmon's own service state and configuration change
DWORD_OR_QWORD = re.compile(r"^(DWORD|QWORD) \(")
BINARY_DATA = "Binary Data"


@dataclass(frozen=True)
class Mapped:
    shape: EventShape
    summary: str
    sections: dict[str, Any]
    tartarus: dict[str, Any] = field(default_factory=dict)


Mapper = Callable[[EventFields], Mapped | None]
MAPPERS: dict[int, Mapper] = {}


def _shape(action: str, category: str, event_type: str, lane: str) -> EventShape:
    return EventShape(action, (category,), (event_type,), lane, DATASET)


PROCESS_CREATED = _shape("process-created", "process", "start", "process")
PROCESS_TERMINATED = _shape("process-terminated", "process", "end", "process")
NETWORK_CONNECTION = _shape("network-connection", "network", "connection", "network")
DNS_QUERY = _shape("dns-query", "network", "protocol", "network")
IMAGE_LOADED = _shape("image-loaded", "process", "info", "process")
CREATE_REMOTE_THREAD = _shape("create-remote-thread", "process", "change", "process")
PROCESS_ACCESSED = _shape("process-access", "process", "access", "process")
FILE_CREATED = _shape("file-created", "file", "creation", "file")
FILE_DELETED = _shape("file-deleted", "file", "deletion", "file")
REG_KEY_CREATED = _shape("reg-key-created", "registry", "creation", "registry")
REG_KEY_DELETED = _shape("reg-key-deleted", "registry", "deletion", "registry")
REG_VALUE_DELETED = _shape("reg-value-deleted", "registry", "deletion", "registry")
REG_VALUE_SET = _shape("reg-value-set", "registry", "change", "registry")
REG_RENAME = _shape("reg-rename", "registry", "change", "registry")
WMI_OPERATION_TYPES = {"Created": "creation", "Deleted": "deletion", "Modified": "change"}


def _maps(*event_ids: int) -> Callable[[Mapper], Mapper]:
    def register(mapper: Mapper) -> Mapper:
        MAPPERS.update(dict.fromkeys(event_ids, mapper))
        return mapper

    return register


def _label(fields: EventFields, prefix: str = "") -> str:
    subject = subject_of(fields, prefix)
    if subject.image:
        return base_name(subject.image)
    return f"pid {subject.pid}" if subject.pid is not None else "a process"


def _file_section(path: str, fields: EventFields) -> dict[str, Any]:
    section = file_fields(path)
    if sha256 := sha256_of(fields):
        section["hash"] = {"sha256": sha256}
    return {"file": section}


def user_section(event_id: int, fields: EventFields) -> dict[str, Any] | None:
    """`DOMAIN\\name` of the acting account, as `user`."""
    prefix = "Source" if event_id in (REMOTE_THREAD, PROCESS_ACCESS) else ""
    account = fields.get(f"{prefix}User")
    if account is None:
        return None
    domain, separator, name = account.rpartition("\\")
    return {"name": name, "domain": domain} if separator and domain else {"name": account}


@_maps(1)
def _process_created(fields: EventFields) -> Mapped | None:
    image = fields.get("Image")
    started = fields.get("CommandLine") or (base_name(image) if image else None)
    if started is None:
        return None
    return Mapped(PROCESS_CREATED, f"{_label(fields, 'Parent')} started {started}", {})


@_maps(5)
def _process_terminated(fields: EventFields) -> Mapped:
    return Mapped(PROCESS_TERMINATED, f"{_label(fields)} terminated", {})


def _endpoint(address: str | None, port: int | None) -> dict[str, Any]:
    if address is None:
        return {}
    return {"ip": address} if port is None else {"ip": address, "port": port}


def _endpoint_text(endpoint: dict[str, Any]) -> str:
    return f"{endpoint['ip']}:{endpoint['port']}" if "port" in endpoint else endpoint["ip"]


@_maps(3)
def _network_connection(fields: EventFields) -> Mapped | None:
    # Sysmon's source and destination are the packet's, not the machine's: for an inbound
    # connection (`Initiated` false) the source is the remote end.
    source = _endpoint(fields.get("SourceIp"), fields.integer("SourcePort"))
    destination = _endpoint(fields.get("DestinationIp"), fields.integer("DestinationPort"))
    if not destination:
        return None
    outbound = fields.get("Initiated") != "false"
    if outbound and (hostname := fields.get("DestinationHostname")):
        destination["domain"] = hostname
    sections: dict[str, Any] = {"destination": destination}
    if source:
        sections["source"] = source
    if protocol := fields.get("Protocol"):
        sections["network"] = {"transport": protocol.lower()}
    label = _label(fields)
    if outbound:
        summary = f"{label} connected to {_endpoint_text(destination)}"
    else:
        summary = f"{label} accepted a connection from {_endpoint_text(source or destination)}"
    return Mapped(NETWORK_CONNECTION, summary, sections)


@_maps(22)
def _dns_query(fields: EventFields) -> Mapped | None:
    name = fields.get("QueryName")
    if name is None:
        return None
    dns: dict[str, Any] = {"question": {"name": name}}
    answers = [answer.strip() for answer in (fields.get("QueryResults") or "").split(";")]
    if data := [answer for answer in answers if answer]:
        dns["answers"] = {"data": data}
    return Mapped(
        DNS_QUERY, f"{_label(fields)} resolved {name}", {"dns": dns, "network": {"protocol": "dns"}}
    )


@_maps(7)
def _image_loaded(fields: EventFields) -> Mapped | None:
    loaded = fields.get("ImageLoaded")
    if loaded is None:
        return None
    return Mapped(IMAGE_LOADED, f"{_label(fields)} loaded {loaded}", _file_section(loaded, fields))


def _target_text(target: Subject) -> str:
    name = base_name(target.image) if target.image else "a process"
    return name if target.pid is None else f"{name} (pid {target.pid})"


def _target_of(fields: EventFields) -> tuple[Subject, dict[str, Any]]:
    """The target process, and the `tartarus.inject` fields that name it."""
    target = subject_of(fields, "Target")
    inject: dict[str, Any] = {}
    if target.pid is not None:
        inject["target_pid"] = target.pid
    if target.image:
        inject["target_name"] = base_name(target.image)
        inject["target_executable"] = target.image
    return target, {"inject": inject} if inject else {}


@_maps(8)
def _create_remote_thread(fields: EventFields) -> Mapped:
    target, inject = _target_of(fields)
    summary = f"{_label(fields, 'Source')} started a thread in {_target_text(target)}"
    return Mapped(CREATE_REMOTE_THREAD, summary, {}, inject)


@_maps(10)
def _process_access(fields: EventFields) -> Mapped:
    target, inject = _target_of(fields)
    access = fields.get("GrantedAccess")
    summary = f"{_label(fields, 'Source')} opened {_target_text(target)}" + (
        f" with access {access}" if access else ""
    )
    return Mapped(PROCESS_ACCESSED, summary, {}, inject)


@_maps(11)
def _file_created(fields: EventFields) -> Mapped | None:
    path = fields.get("TargetFilename")
    if path is None:
        return None
    return Mapped(FILE_CREATED, f"{_label(fields)} created {path}", _file_section(path, fields))


@_maps(23, 26)
def _file_deleted(fields: EventFields) -> Mapped | None:
    path = fields.get("TargetFilename")
    if path is None:
        return None
    return Mapped(FILE_DELETED, f"{_label(fields)} deleted {path}", _file_section(path, fields))


REGISTRY_OBJECT_EVENTS = {
    "CreateKey": (REG_KEY_CREATED, "created key", False),
    "DeleteKey": (REG_KEY_DELETED, "deleted key", False),
    "DeleteValue": (REG_VALUE_DELETED, "deleted value", True),
}


@_maps(12)
def _registry_object(fields: EventFields) -> Mapped | None:
    path = fields.get("TargetObject")
    handled = REGISTRY_OBJECT_EVENTS.get(fields.get("EventType") or "")
    if path is None or handled is None:
        return None
    shape, verb, names_value = handled
    registry = registry_fields(path, value_name=base_name(path) if names_value else None)
    return Mapped(shape, f"{_label(fields)} {verb} {path}", {"registry": registry})


def _value_type(details: str) -> str | None:
    if match := DWORD_OR_QWORD.match(details):
        return f"REG_{match[1]}"
    return "REG_BINARY" if details == BINARY_DATA else None


@_maps(13)
def _registry_value_set(fields: EventFields) -> Mapped | None:
    path = fields.get("TargetObject")
    if path is None:
        return None
    details = fields.get("Details")
    registry = registry_fields(
        path,
        value_name=base_name(path),
        data_type=_value_type(details) if details else None,
        data=details,
    )
    return Mapped(REG_VALUE_SET, f"{_label(fields)} set {path}", {"registry": registry})


@_maps(14)
def _registry_renamed(fields: EventFields) -> Mapped | None:
    path = fields.get("TargetObject")
    if path is None:
        return None
    new_name = fields.get("NewName")
    summary = f"{_label(fields)} renamed {path}" + (f" to {new_name}" if new_name else "")
    return Mapped(REG_RENAME, summary, {"registry": registry_fields(path)})


def _wmi_shape(action: str, fields: EventFields) -> EventShape:
    operation = fields.get("Operation") or ""
    return _shape(action, "process", WMI_OPERATION_TYPES.get(operation, "change"), "process")


def _operation(fields: EventFields) -> str:
    return (fields.get("Operation") or "changed").lower()


@_maps(19)
def _wmi_filter(fields: EventFields) -> Mapped:
    namespace, query = fields.get("EventNamespace"), fields.get("Query")
    summary = f"WMI event filter {fields.get('Name') or '?'} {_operation(fields)}"
    summary += f" in {namespace}" if namespace else ""
    summary += f": {query}" if query else ""
    return Mapped(_wmi_shape("wmi-filter", fields), summary, {})


@_maps(20)
def _wmi_consumer(fields: EventFields) -> Mapped:
    kind, destination = fields.get("Type"), fields.get("Destination")
    summary = f"WMI event consumer {fields.get('Name') or '?'}"
    summary += f" ({kind})" if kind else ""
    summary += f" {_operation(fields)}"
    summary += f": {destination}" if destination else ""
    return Mapped(_wmi_shape("wmi-consumer", fields), summary, {})


@_maps(21)
def _wmi_binding(fields: EventFields) -> Mapped:
    summary = (
        f"WMI binding of {fields.get('Consumer') or '?'} to {fields.get('Filter') or '?'} "
        f"{_operation(fields)}"
    )
    return Mapped(_wmi_shape("wmi-binding", fields), summary, {})
