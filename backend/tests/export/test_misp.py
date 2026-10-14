import json
import uuid
from typing import Any

from app.export.inputs import ExportAnnotations, ExportNote, TargetType
from app.export.misp import build_event
from app.schemas.views_findings import IocType
from tests.export.conftest import (
    DROPPED_SHA256,
    EVERY_TYPE,
    NOTES,
    SAMPLE_MD5,
    SAMPLE_SHA1,
    SAMPLE_SHA256,
    make_ioc,
)
from tests.export.validation import misp_problems


def attributes(document: dict[str, Any]) -> list[dict[str, Any]]:
    return document["Event"]["Attribute"]


def tags(document: dict[str, Any]) -> list[str]:
    return [tag["name"] for tag in document["Event"]["Tag"]]


def by_type(document: dict[str, Any], type_: str) -> list[dict[str, Any]]:
    return [attribute for attribute in attributes(document) if attribute["type"] == type_]


def test_the_event_passes_the_misp_schema_and_the_required_key_checks(make_input) -> None:
    assert misp_problems(build_event(make_input())) == []


def test_an_empty_ioc_set_is_still_a_valid_event(make_input) -> None:
    document = build_event(make_input(iocs=(), techniques=(), annotations=ExportAnnotations()))

    assert misp_problems(document) == []
    assert document["Event"]["Attribute"] == []
    assert tags(document) == ["tlp:amber"]


def test_the_info_names_the_analysis_and_the_file(make_input) -> None:
    event = build_event(make_input())["Event"]

    assert event["info"] == "Tartarus analysis #7 \N{EN DASH} invoice.exe"
    assert event["date"] == "2026-10-13"
    assert event["timestamp"] == "1791894615"
    assert event["published"] is False


def test_every_ioc_type_is_an_attribute_of_the_misp_type_and_category(make_input) -> None:
    document = build_event(make_input())

    shape = {(a["type"], a["value"]): (a["category"], a["to_ids"]) for a in attributes(document)}

    assert shape[("sha256", SAMPLE_SHA256)] == ("Payload delivery", True)
    assert shape[("sha256", DROPPED_SHA256)] == ("Payload delivery", True)
    assert shape[("domain", "evil.example")] == ("Network activity", True)
    assert shape[("ip-dst", "203.0.113.7")] == ("Network activity", True)
    assert shape[("ip-dst", "2001:db8::1")] == ("Network activity", True)
    assert shape[("url", "http://evil.example/a.php?x=1&y='2'")] == ("Network activity", True)
    assert shape[("mutex", "Global\\Tartarus-Mutex")] == ("Artifacts dropped", False)
    registry = next(ioc.value for ioc in EVERY_TYPE if ioc.type is IocType.REGISTRY)
    assert shape[("regkey", registry)] == ("Persistence mechanism", False)
    file_path = next(ioc.value for ioc in EVERY_TYPE if ioc.type is IocType.FILE)
    assert shape[("filename", file_path)] == ("Artifacts dropped", False)


def test_the_context_is_the_attribute_comment(make_input) -> None:
    domain = by_type(build_event(make_input()), "domain")[0]

    assert domain["comment"] == "DNS query evil.example"


def test_the_sample_also_carries_its_md5_and_sha1(make_input) -> None:
    document = build_event(make_input())

    assert [a["value"] for a in by_type(document, "md5")] == [SAMPLE_MD5]
    assert [a["value"] for a in by_type(document, "sha1")] == [SAMPLE_SHA1]
    assert by_type(document, "md5")[0]["to_ids"] is True


def test_a_sample_hash_missing_from_the_iocs_adds_no_md5(make_input) -> None:
    document = build_event(make_input(iocs=(make_ioc(IocType.DOMAIN, "a.example"),)))

    assert by_type(document, "md5") == []


def test_a_hash_seen_twice_is_one_attribute(make_input) -> None:
    twice = (
        make_ioc(IocType.HASH, DROPPED_SHA256, "Dropped file a"),
        make_ioc(IocType.HASH, DROPPED_SHA256, "Payload a"),
    )

    assert len(by_type(build_event(make_input(iocs=twice)), "sha256")) == 1


def test_tlp_amber_is_the_default_marking(make_input) -> None:
    assert tags(build_event(make_input()))[0] == "tlp:amber"


def test_the_analysts_tlp_tag_replaces_the_default(make_input) -> None:
    document = build_event(make_input(annotations=ExportAnnotations(tags=("phishing", "tlp:red"))))

    assert tags(document)[:2] == ["tlp:red", "phishing"]
    assert "tlp:amber" not in tags(document)


def test_the_analysts_tags_are_misp_tags(make_input) -> None:
    assert {"phishing", "needs-review"} <= set(tags(build_event(make_input())))


def test_attack_techniques_known_to_the_table_become_galaxy_tags(make_input) -> None:
    galaxy = [t for t in tags(build_event(make_input())) if t.startswith("misp-galaxy:")]

    assert galaxy == [
        'misp-galaxy:mitre-attack-pattern="Command and Scripting Interpreter - T1059"',
        'misp-galaxy:mitre-attack-pattern="Registry Run Keys / Startup Folder - T1547.001"',
    ]


def test_notes_become_comment_attributes_saying_what_they_are_about(make_input) -> None:
    comments = by_type(build_event(make_input()), "comment")

    assert [(a["value"], a["comment"]) for a in comments] == [
        ("Looks like an Emotet dropper.", "Analyst note on the analysis"),
        ("Spawns the DNS lookups.", "Analyst note on process 4242"),
        ("The beacon, check the URI.", "Analyst note on event ev-dns"),
    ]
    assert not any(a["to_ids"] for a in comments)


def test_the_same_note_twice_is_one_attribute(make_input) -> None:
    twice = ExportAnnotations(notes=(NOTES[0], NOTES[0]))

    assert len(by_type(build_event(make_input(annotations=twice)), "comment")) == 1


def test_unicode_is_kept_and_the_event_still_validates(make_input) -> None:
    note = ExportNote("Zażółć gęślą jaźń 日本語", TargetType.ANALYSIS, None)
    document = build_event(
        make_input(
            iocs=(make_ioc(IocType.DOMAIN, "пример.рф"),),
            annotations=ExportAnnotations(notes=(note,)),
        )
    )

    assert misp_problems(document) == []
    assert by_type(document, "domain")[0]["value"] == "пример.рф"
    assert by_type(document, "comment")[0]["value"] == "Zażółć gęślą jaźń 日本語"


def test_the_same_input_gives_the_same_event(make_input) -> None:
    assert build_event(make_input()) == build_event(make_input())


def test_uuids_are_valid_and_per_analysis(make_input) -> None:
    first = build_event(make_input(analysis_id=1))
    second = build_event(make_input(analysis_id=2))

    for item in (first["Event"], *attributes(first)):
        assert str(uuid.UUID(item["uuid"])) == item["uuid"]
    assert first["Event"]["uuid"] != second["Event"]["uuid"]
    assert {a["uuid"] for a in attributes(first)}.isdisjoint(a["uuid"] for a in attributes(second))


def test_the_event_serialises_to_json(make_input) -> None:
    document = build_event(make_input())

    assert json.loads(json.dumps(document)) == document
