from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.export.identifiers import stable_uuid
from app.export.inputs import ExportNote, ExportTechnique, IocExportInput
from app.schemas.views_findings import Ioc, IocType

EN_DASH = "\N{EN DASH}"
DEFAULT_TLP = "tlp:amber"
THREAT_LEVEL_UNDEFINED = "4"
ANALYSIS_COMPLETED = "2"
ORGANISATION_ONLY = "0"
INHERIT_FROM_EVENT = "5"
GALAXY_TAG = 'misp-galaxy:mitre-attack-pattern="{name} - {id}"'

Attribute = dict[str, Any]


@dataclass(frozen=True)
class _AttributeKind:
    type: str
    category: str
    to_ids: bool


ATTRIBUTE_KINDS = {
    IocType.HASH: _AttributeKind("sha256", "Payload delivery", True),
    IocType.DOMAIN: _AttributeKind("domain", "Network activity", True),
    IocType.IP: _AttributeKind("ip-dst", "Network activity", True),
    IocType.URL: _AttributeKind("url", "Network activity", True),
    IocType.MUTEX: _AttributeKind("mutex", "Artifacts dropped", False),
    IocType.REGISTRY: _AttributeKind("regkey", "Persistence mechanism", False),
    IocType.FILE: _AttributeKind("filename", "Artifacts dropped", False),
}
SAMPLE_HASH_KINDS = {
    "md5": _AttributeKind("md5", "Payload delivery", True),
    "sha1": _AttributeKind("sha1", "Payload delivery", True),
}
NOTE_KIND = _AttributeKind("comment", "Other", False)


def build_event(inputs: IocExportInput) -> dict[str, Any]:
    stamp = _epoch(inputs.observed_at)
    attributes = _unique(
        [*_ioc_attributes(inputs, stamp), *_note_attributes(inputs, stamp)],
    )
    return {
        "Event": {
            "uuid": stable_uuid(inputs.analysis_id, "event"),
            "info": f"Tartarus analysis #{inputs.analysis_id} {EN_DASH} {inputs.sample.filename}",
            "date": inputs.observed_at.date().isoformat(),
            "timestamp": stamp,
            "analysis": ANALYSIS_COMPLETED,
            "threat_level_id": THREAT_LEVEL_UNDEFINED,
            "distribution": ORGANISATION_ONLY,
            "published": False,
            "Tag": [{"name": name} for name in _tag_names(inputs)],
            "Attribute": attributes,
        }
    }


def _epoch(moment: datetime) -> str:
    return str(int(moment.timestamp()))


def _attribute(
    inputs: IocExportInput, kind: _AttributeKind, value: str, comment: str, stamp: str
) -> Attribute:
    return {
        "uuid": stable_uuid(inputs.analysis_id, "attribute", kind.type, value),
        "type": kind.type,
        "category": kind.category,
        "value": value,
        "to_ids": kind.to_ids,
        "comment": comment,
        "distribution": INHERIT_FROM_EVENT,
        "timestamp": stamp,
    }


def _unique(attributes: list[Attribute]) -> list[Attribute]:
    first_of_each: dict[tuple[str, str], Attribute] = {}
    for attribute in attributes:
        first_of_each.setdefault((attribute["type"], attribute["value"]), attribute)
    return list(first_of_each.values())


def _ioc_attributes(inputs: IocExportInput, stamp: str) -> list[Attribute]:
    attributes: list[Attribute] = []
    for ioc in inputs.distinct_iocs:
        attributes.append(
            _attribute(inputs, ATTRIBUTE_KINDS[ioc.type], ioc.value, ioc.context, stamp)
        )
        if _is_sample(inputs, ioc):
            attributes.extend(_sample_hash_attributes(inputs, ioc, stamp))
    return attributes


def _is_sample(inputs: IocExportInput, ioc: Ioc) -> bool:
    return ioc.type is IocType.HASH and ioc.value.lower() == inputs.sample.sha256.lower()


def _sample_hash_attributes(inputs: IocExportInput, ioc: Ioc, stamp: str) -> list[Attribute]:
    other_hashes = {"md5": inputs.sample.md5, "sha1": inputs.sample.sha1}
    return [
        _attribute(inputs, SAMPLE_HASH_KINDS[name], value, ioc.context, stamp)
        for name, value in other_hashes.items()
        if value
    ]


def _note_attributes(inputs: IocExportInput, stamp: str) -> list[Attribute]:
    return [_note_attribute(inputs, note, stamp) for note in inputs.annotations.notes]


def _note_attribute(inputs: IocExportInput, note: ExportNote, stamp: str) -> Attribute:
    return _attribute(inputs, NOTE_KIND, note.body, note.label, stamp)


def _tag_names(inputs: IocExportInput) -> list[str]:
    annotations = inputs.annotations
    tlp = annotations.tlp_tag or DEFAULT_TLP
    analyst = sorted(tag for tag in annotations.tags if tag != tlp and not _is_tlp(tag))
    return [tlp, *analyst, *_galaxy_tags(inputs.techniques)]


def _is_tlp(tag: str) -> bool:
    return tag.startswith("tlp:")


def _galaxy_tags(techniques: tuple[ExportTechnique, ...]) -> list[str]:
    return [
        GALAXY_TAG.format(name=technique.name, id=technique.id)
        for technique in techniques
        if technique.name is not None
    ]
