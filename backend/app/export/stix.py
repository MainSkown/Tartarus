import ipaddress
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.export.identifiers import stable_uuid
from app.export.inputs import ExportNote, ExportSample, ExportTechnique, IocExportInput, TargetType
from app.schemas.views_findings import Ioc, IocType

SPEC_VERSION = "2.1"
# STIX 2.1 section 2.9: a cyber-observable's id is a UUIDv5 of its identifying properties
# under this namespace, so every producer gives the same file the same id.
SCO_NAMESPACE = uuid.UUID("00abedb4-aa42-466c-9c01-fed23315a9b7")
IDENTITY_NAME = "Tartarus"
# The identity is the same in every bundle, so its timestamps cannot depend on the analysis.
IDENTITY_TIMESTAMP = "2026-10-01T00:00:00.000Z"
# Section 2.9 again: only one hash identifies a file, the first of these that is present.
ID_HASH_PREFERENCE = ("MD5", "SHA-1", "SHA-256")
UNKNOWN_MALWARE = "unknown"
ATTACK_URL = "https://attack.mitre.org/techniques/"

SDO = dict[str, Any]


@dataclass(frozen=True)
class _Context:
    analysis_id: int
    stamp: str
    identity_id: str

    def object(self, type_: str, *seed: object, **fields: Any) -> SDO:
        return {
            "type": type_,
            "spec_version": SPEC_VERSION,
            "id": f"{type_}--{stable_uuid(self.analysis_id, type_, *seed)}",
            "created_by_ref": self.identity_id,
            "created": self.stamp,
            "modified": self.stamp,
            **fields,
        }


def build_bundle(inputs: IocExportInput) -> dict[str, Any]:
    identity = _identity()
    context = _Context(inputs.analysis_id, _timestamp(inputs.observed_at), identity["id"])
    malware = [_malware(context, family) for family in inputs.families] or [
        _malware(context, UNKNOWN_MALWARE, is_family=False)
    ]
    techniques = [_attack_pattern(context, technique) for technique in inputs.techniques]
    iocs = inputs.distinct_iocs
    files = [_file(ioc, inputs.sample) for ioc in iocs if ioc.type is IocType.HASH]
    indicators = [(ioc, _indicator(context, ioc)) for ioc in iocs if _pattern(ioc)]
    malware_ids = [item["id"] for item in malware]
    relationships = [
        *_relationships(context, "indicates", [i["id"] for _, i in indicators], malware_ids),
        *_relationships(context, "uses", malware_ids, [item["id"] for item in techniques]),
    ]
    notes = _notes(context, inputs, malware_ids, indicators)
    objects = [
        identity,
        *malware,
        *techniques,
        *files,
        *(indicator for _, indicator in indicators),
        *relationships,
        *notes,
    ]
    return {
        "type": "bundle",
        "id": f"bundle--{stable_uuid(inputs.analysis_id, 'bundle')}",
        "objects": objects,
    }


def _timestamp(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _identity() -> SDO:
    return {
        "type": "identity",
        "spec_version": SPEC_VERSION,
        "id": f"identity--{stable_uuid('identity', IDENTITY_NAME)}",
        "created": IDENTITY_TIMESTAMP,
        "modified": IDENTITY_TIMESTAMP,
        "name": IDENTITY_NAME,
        "identity_class": "system",
    }


def _malware(context: _Context, name: str, is_family: bool = True) -> SDO:
    return context.object("malware", name, name=name, is_family=is_family)


def _attack_pattern(context: _Context, technique: ExportTechnique) -> SDO:
    return context.object(
        "attack-pattern",
        technique.id,
        name=technique.name or technique.id,
        external_references=[
            {
                "source_name": "mitre-attack",
                "external_id": technique.id,
                "url": f"{ATTACK_URL}{technique.id.replace('.', '/')}/",
            }
        ],
    )


def _file(ioc: Ioc, sample: ExportSample) -> SDO:
    sha256 = ioc.value.lower()
    fields: dict[str, Any] = {"hashes": {"SHA-256": sha256}}
    if sha256 == sample.sha256.lower():
        hashes = {"SHA-256": sha256, "MD5": sample.md5, "SHA-1": sample.sha1}
        fields = {
            "hashes": {algorithm: value for algorithm, value in hashes.items() if value},
            "name": sample.filename,
        }
    return {
        "type": "file",
        "spec_version": SPEC_VERSION,
        "id": f"file--{_deterministic_file_uuid(fields)}",
        **fields,
    }


def _deterministic_file_uuid(fields: dict[str, Any]) -> uuid.UUID:
    identifying = {**fields, "hashes": _one_hash(fields["hashes"])}
    canonical = json.dumps(identifying, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return uuid.uuid5(SCO_NAMESPACE, canonical)


def _one_hash(hashes: dict[str, str]) -> dict[str, str]:
    algorithm = next(name for name in ID_HASH_PREFERENCE if name in hashes)
    return {algorithm: hashes[algorithm]}


def _indicator(context: _Context, ioc: Ioc) -> SDO:
    return context.object(
        "indicator",
        ioc.type,
        ioc.value.casefold(),
        name=f"{ioc.type.value}: {ioc.value}",
        description=ioc.context,
        pattern=_pattern(ioc),
        pattern_type="stix",
        valid_from=context.stamp,
    )


def _pattern(ioc: Ioc) -> str | None:
    comparison = _comparison(ioc)
    return None if comparison is None else f"[{comparison}]"


def _comparison(ioc: Ioc) -> str | None:
    match ioc.type:
        case IocType.HASH:
            return f"file:hashes.'SHA-256' = {_literal(ioc.value.lower())}"
        case IocType.DOMAIN:
            return f"domain-name:value = {_literal(ioc.value)}"
        case IocType.URL:
            return f"url:value = {_literal(ioc.value)}"
        case IocType.IP:
            return _address_comparison(ioc.value)
        case _:
            return None


def _address_comparison(value: str) -> str | None:
    try:
        version = ipaddress.ip_address(value).version
    except ValueError:
        return None
    return f"ipv{version}-addr:value = {_literal(value)}"


def _literal(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"


def _relationships(
    context: _Context, kind: str, source_ids: list[str], target_ids: list[str]
) -> list[SDO]:
    return [
        context.object(
            "relationship",
            source,
            kind,
            target,
            relationship_type=kind,
            source_ref=source,
            target_ref=target,
        )
        for source in source_ids
        for target in target_ids
    ]


def _notes(
    context: _Context,
    inputs: IocExportInput,
    malware_ids: list[str],
    indicators: list[tuple[Ioc, SDO]],
) -> list[SDO]:
    notes = {
        note["id"]: note
        for note in (
            _note(context, note, malware_ids, indicators) for note in inputs.annotations.notes
        )
    }
    return list(notes.values())


def _note(
    context: _Context,
    note: ExportNote,
    malware_ids: list[str],
    indicators: list[tuple[Ioc, SDO]],
) -> SDO:
    related = [indicator["id"] for ioc, indicator in indicators if _is_about(note, ioc)]
    return context.object(
        "note",
        note.target_type,
        note.target_ref,
        note.body,
        abstract=note.label,
        content=note.body,
        object_refs=[*malware_ids, *related],
    )


def _is_about(note: ExportNote, ioc: Ioc) -> bool:
    match note.target_type:
        case TargetType.PROCESS:
            return ioc.process is not None and str(ioc.process.pid) == note.target_ref
        case TargetType.EVENT:
            return note.target_ref in ioc.source_event_ids
        case _:
            return False
