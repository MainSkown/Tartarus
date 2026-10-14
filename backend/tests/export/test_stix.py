import json
from typing import Any

import stix2

from app.export.inputs import ExportAnnotations, ExportNote, TargetType
from app.export.stix import build_bundle
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
from tests.export.validation import parse_stix


def of_type(bundle: dict[str, Any], type_: str) -> list[dict[str, Any]]:
    return [item for item in bundle["objects"] if item["type"] == type_]


def indicator_patterns(bundle: dict[str, Any]) -> set[str]:
    return {item["pattern"] for item in of_type(bundle, "indicator")}


def test_the_bundle_is_valid_stix_for_the_reference_parser(make_input) -> None:
    bundle = build_bundle(make_input())

    parsed = parse_stix(bundle)

    assert len(parsed.objects) == len(bundle["objects"])


def test_an_empty_ioc_set_is_still_a_valid_bundle(make_input) -> None:
    bundle = build_bundle(make_input(iocs=(), techniques=(), annotations=ExportAnnotations()))

    parse_stix(bundle)
    assert {item["type"] for item in bundle["objects"]} == {"identity", "malware"}


def test_the_identity_is_tartarus_and_the_same_in_every_bundle(make_input) -> None:
    first = of_type(build_bundle(make_input(analysis_id=1)), "identity")
    second = of_type(build_bundle(make_input(analysis_id=2)), "identity")

    assert first == second
    assert first[0]["name"] == "Tartarus"
    assert first[0]["identity_class"] == "system"


def test_hashes_domains_ips_and_urls_become_indicators(make_input) -> None:
    patterns = indicator_patterns(build_bundle(make_input()))

    assert patterns == {
        f"[file:hashes.'SHA-256' = '{SAMPLE_SHA256}']",
        f"[file:hashes.'SHA-256' = '{DROPPED_SHA256}']",
        "[domain-name:value = 'evil.example']",
        "[ipv4-addr:value = '203.0.113.7']",
        "[ipv6-addr:value = '2001:db8::1']",
        "[url:value = 'http://evil.example/a.php?x=1&y=\\'2\\'']",
    }


def test_mutexes_registry_keys_and_file_paths_are_left_out(make_input) -> None:
    bundle = build_bundle(make_input())

    assert {item["type"] for item in bundle["objects"]} == {
        "identity",
        "malware",
        "attack-pattern",
        "file",
        "indicator",
        "relationship",
        "note",
    }
    assert not any("Mutex" in pattern or "Run" in pattern for pattern in indicator_patterns(bundle))


def test_an_indicator_is_valid_from_the_analysis_time(make_input) -> None:
    indicators = of_type(build_bundle(make_input()), "indicator")

    assert {item["valid_from"] for item in indicators} == {"2026-10-13T12:30:15.250Z"}
    assert {item["created"] for item in indicators} == {"2026-10-13T12:30:15.250Z"}


def test_an_indicator_names_what_it_matches_and_where_it_came_from(make_input) -> None:
    domain = next(
        item
        for item in of_type(build_bundle(make_input()), "indicator")
        if "domain-name" in item["pattern"]
    )

    assert domain["name"] == "domain: evil.example"
    assert domain["description"] == "DNS query evil.example"
    assert domain["pattern_type"] == "stix"


def test_the_samples_file_object_carries_its_name_and_all_three_hashes(make_input) -> None:
    files = {
        item["hashes"]["SHA-256"]: item for item in of_type(build_bundle(make_input()), "file")
    }

    assert files[SAMPLE_SHA256]["name"] == "invoice.exe"
    assert files[SAMPLE_SHA256]["hashes"] == {
        "SHA-256": SAMPLE_SHA256,
        "MD5": SAMPLE_MD5,
        "SHA-1": SAMPLE_SHA1,
    }
    assert files[DROPPED_SHA256]["hashes"] == {"SHA-256": DROPPED_SHA256}
    assert "name" not in files[DROPPED_SHA256]


def test_a_file_object_has_the_id_the_stix_spec_derives_from_its_properties(make_input) -> None:
    files = {
        item["hashes"]["SHA-256"]: item for item in of_type(build_bundle(make_input()), "file")
    }

    assert files[DROPPED_SHA256]["id"] == stix2.File(hashes={"SHA-256": DROPPED_SHA256}).id
    assert (
        files[SAMPLE_SHA256]["id"]
        == stix2.File(
            hashes={"SHA-256": SAMPLE_SHA256, "MD5": SAMPLE_MD5, "SHA-1": SAMPLE_SHA1},
            name="invoice.exe",
        ).id
    )


def test_a_hash_seen_twice_is_one_file_and_one_indicator(make_input) -> None:
    twice = (
        make_ioc(IocType.HASH, DROPPED_SHA256, "Dropped file a"),
        make_ioc(IocType.HASH, DROPPED_SHA256, "Payload a"),
    )

    bundle = build_bundle(make_input(iocs=twice))

    assert len(of_type(bundle, "file")) == 1
    assert len(of_type(bundle, "indicator")) == 1


def test_each_detected_family_is_a_malware_family(make_input) -> None:
    bundle = build_bundle(make_input(families=("emotet", "qakbot")))

    malware = of_type(bundle, "malware")

    assert [(item["name"], item["is_family"]) for item in malware] == [
        ("emotet", True),
        ("qakbot", True),
    ]


def test_without_a_family_there_is_one_unknown_malware_that_is_not_a_family(make_input) -> None:
    malware = of_type(build_bundle(make_input(families=())), "malware")

    assert [(item["name"], item["is_family"]) for item in malware] == [("unknown", False)]


def test_every_technique_is_an_attack_pattern_with_its_mitre_reference(make_input) -> None:
    patterns = {
        item["name"]: item for item in of_type(build_bundle(make_input()), "attack-pattern")
    }

    assert set(patterns) == {
        "Command and Scripting Interpreter",
        "Registry Run Keys / Startup Folder",
        "T9999",
    }
    assert patterns["Registry Run Keys / Startup Folder"]["external_references"] == [
        {
            "source_name": "mitre-attack",
            "external_id": "T1547.001",
            "url": "https://attack.mitre.org/techniques/T1547/001/",
        }
    ]


def test_indicators_indicate_the_malware_and_the_malware_uses_the_techniques(make_input) -> None:
    bundle = build_bundle(make_input())
    kind = {item["id"]: item["type"] for item in bundle["objects"]}

    edges = {
        (kind[rel["source_ref"]], rel["relationship_type"], kind[rel["target_ref"]])
        for rel in of_type(bundle, "relationship")
    }

    assert edges == {("indicator", "indicates", "malware"), ("malware", "uses", "attack-pattern")}
    assert len(of_type(bundle, "relationship")) == 6 + 3


def test_with_several_families_each_indicator_indicates_each(make_input) -> None:
    bundle = build_bundle(make_input(families=("a", "b"), techniques=()))

    assert len(of_type(bundle, "relationship")) == 6 * 2


def test_every_reference_resolves_inside_the_bundle(make_input) -> None:
    bundle = build_bundle(make_input())
    ids = {item["id"] for item in bundle["objects"]}

    for item in bundle["objects"]:
        refs = [value for key, value in item.items() if key.endswith("_ref")]
        refs += [ref for key, group in item.items() if key.endswith("_refs") for ref in group]
        assert set(refs) <= ids, item["type"]


def test_the_analysts_notes_are_note_objects_attached_to_what_they_are_about(make_input) -> None:
    bundle = build_bundle(make_input())
    by_id = {item["id"]: item for item in bundle["objects"]}
    notes = {item["content"]: item for item in of_type(bundle, "note")}

    assert set(notes) == {note.body for note in NOTES}

    analysis = notes["Looks like an Emotet dropper."]
    assert [by_id[ref]["type"] for ref in analysis["object_refs"]] == ["malware"]

    process = notes["Spawns the DNS lookups."]
    assert {by_id[ref]["type"] for ref in process["object_refs"]} == {"malware", "indicator"}
    assert len(process["object_refs"]) == 1 + 5  # the five IOCs of process 4242 that are indicators

    event = notes["The beacon, check the URI."]
    attached = [by_id[ref] for ref in event["object_refs"] if by_id[ref]["type"] == "indicator"]
    assert [item["pattern"] for item in attached] == ["[domain-name:value = 'evil.example']"]


def test_a_note_says_what_it_is_about_in_its_abstract(make_input) -> None:
    abstracts = {item["abstract"] for item in of_type(build_bundle(make_input()), "note")}

    assert abstracts == {
        "Analyst note on the analysis",
        "Analyst note on process 4242",
        "Analyst note on event ev-dns",
    }


def test_without_notes_there_are_no_note_objects(make_input) -> None:
    bundle = build_bundle(make_input(annotations=ExportAnnotations(tags=("phishing",))))

    assert of_type(bundle, "note") == []


def test_unicode_and_quotes_survive_into_valid_patterns_and_notes(make_input) -> None:
    iocs = (
        make_ioc(IocType.DOMAIN, "пример.рф"),
        make_ioc(IocType.URL, "http://a.example/it's\\here"),
    )
    notes = ExportAnnotations(notes=(ExportNote('Zażółć "gęślą" jaźń', TargetType.ANALYSIS, None),))

    bundle = build_bundle(make_input(iocs=iocs, annotations=notes))

    parse_stix(bundle)
    assert "[domain-name:value = 'пример.рф']" in indicator_patterns(bundle)
    assert of_type(bundle, "note")[0]["content"] == 'Zażółć "gęślą" jaźń'


def test_the_same_input_gives_the_same_bundle(make_input) -> None:
    assert build_bundle(make_input()) == build_bundle(make_input())


def test_another_analysis_gives_other_ids_but_the_same_file_object(make_input) -> None:
    first = build_bundle(make_input(analysis_id=1))
    second = build_bundle(make_input(analysis_id=2))

    def analysis_bound_ids(bundle):
        return {
            item["id"] for item in bundle["objects"] if item["type"] not in ("file", "identity")
        }

    assert analysis_bound_ids(first).isdisjoint(analysis_bound_ids(second))
    assert of_type(first, "file") == of_type(second, "file")


def test_timestamps_come_from_the_analysis_not_the_clock(make_input) -> None:
    bundle = build_bundle(make_input())

    stamps = {item["created"] for item in bundle["objects"] if "created" in item}
    assert "2026-10-13T12:30:15.250Z" in stamps


def test_the_bundle_serialises_to_json(make_input) -> None:
    assert json.loads(json.dumps(build_bundle(make_input()))) == build_bundle(make_input())


def test_every_ioc_type_is_in_the_fixture() -> None:
    assert {ioc.type for ioc in EVERY_TYPE} == set(IocType)
