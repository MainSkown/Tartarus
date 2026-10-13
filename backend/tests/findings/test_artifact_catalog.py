import re
from pathlib import Path
from typing import Any

from app.views.artifacts import build_catalog, download_name
from tests.findings.conftest import DROPPED_SHA256, PCAP_SHA256, PROCDUMP_SHA256, put_file

OPAQUE_ID = re.compile(r"[0-9a-f]{20}")


def payload(sha256: str, name: str = "stage2.bin", **extra: Any) -> dict[str, Any]:
    return {
        "name": name,
        "sha256": sha256,
        "md5": "0" * 32,
        "size": 5,
        "type": "data",
        "cape_type": "Cobalt Strike Beacon",
        "pid": 10116,
        "guest_paths": ["C:\\Temp\\stage2.bin"],
        "cape_yara": [{"name": "CobaltStrike"}],
        "yara": [{"name": "generic"}, "plain_name"],
        **extra,
    }


def test_dropped_files_come_from_the_report_with_their_writer(
    report: dict[str, Any], analysis_dir: Path
) -> None:
    dropped = build_catalog(report, analysis_dir).view.dropped

    assert [artifact.name for artifact in dropped] == ["tartarus-benign.txt"]
    only = dropped[0]
    assert (only.sha256, only.size, only.md5) == (
        DROPPED_SHA256,
        33,
        "fba3232a4e0d640527227f4465942beb",
    )
    assert only.guest_path == "C:\\Users\\Analyst\\AppData\\Local\\Temp\\tartarus-benign.txt"
    assert only.source_process is not None
    assert (only.source_process.pid, only.source_process.name) == (10116, "benign.exe")


def test_process_dumps_are_named_after_their_process(
    report: dict[str, Any], analysis_dir: Path
) -> None:
    procdumps = build_catalog(report, analysis_dir).view.procdumps

    assert [dump.name for dump in procdumps] == ["benign.exe", "cmd.exe"]
    assert procdumps[0].sha256 == PROCDUMP_SHA256
    assert procdumps[0].guest_path == "C:\\Users\\Analyst\\AppData\\Local\\Temp\\benign.exe"


def test_payloads_and_configs_come_from_the_cape_section(
    report: dict[str, Any], analysis_dir: Path
) -> None:
    report["CAPE"] = {
        "payloads": [payload("a" * 64)],
        "configs": [{"CobaltStrikeBeacon": {"C2Server": "evil.example"}}],
    }

    view = build_catalog(report, analysis_dir).view

    assert [item.cape_type for item in view.payloads] == ["Cobalt Strike Beacon"]
    assert view.payloads[0].yara == ["generic", "plain_name", "CobaltStrike"]
    assert [(config.family, config.data) for config in view.configs] == [
        ("CobaltStrikeBeacon", {"C2Server": "evil.example"})
    ]


def test_an_artifact_id_is_opaque_and_stable(report: dict[str, Any], analysis_dir: Path) -> None:
    first = build_catalog(report, analysis_dir).view.dropped[0].id
    second = build_catalog(report, analysis_dir).view.dropped[0].id

    assert first == second
    assert OPAQUE_ID.fullmatch(first)


def test_the_same_hash_as_another_kind_gets_another_id(
    report: dict[str, Any], analysis_dir: Path
) -> None:
    report["CAPE"] = {"payloads": [payload(DROPPED_SHA256)], "configs": []}

    view = build_catalog(report, analysis_dir).view

    assert view.payloads[0].id != view.dropped[0].id


def test_a_hash_listed_twice_in_one_kind_gets_two_ids(
    report: dict[str, Any], analysis_dir: Path
) -> None:
    report["dropped"] = [report["dropped"][0], report["dropped"][0]]

    ids = [artifact.id for artifact in build_catalog(report, analysis_dir).view.dropped]

    assert len(set(ids)) == 2


def test_an_artifact_is_downloadable_only_when_its_file_is_in_the_analysis_folder(
    report: dict[str, Any], analysis_dir: Path
) -> None:
    put_file(analysis_dir, f"files/{DROPPED_SHA256}", b"tartarus benign sample was here\n")

    catalog = build_catalog(report, analysis_dir)

    assert [a.downloadable for a in catalog.view.dropped] == [True]
    assert [a.downloadable for a in catalog.view.procdumps] == [False, False]
    assert set(catalog.files) == {catalog.view.dropped[0].id}


def test_the_file_location_comes_from_the_hash_never_from_the_report_path(
    report: dict[str, Any], analysis_dir: Path, tmp_path: Path
) -> None:
    secret = put_file(tmp_path, "secret.txt", b"top secret")
    report["dropped"][0]["path"] = str(secret)

    catalog = build_catalog(report, analysis_dir)

    assert catalog.view.dropped[0].downloadable is False
    assert catalog.files == {}


def test_a_hash_that_is_not_a_sha256_cannot_name_a_file(
    report: dict[str, Any], analysis_dir: Path, tmp_path: Path
) -> None:
    put_file(tmp_path, "secret", b"top secret")
    report["dropped"][0]["sha256"] = "../../../../secret"

    catalog = build_catalog(report, analysis_dir)

    assert catalog.view.dropped[0].downloadable is False
    assert catalog.files == {}


def test_a_link_leading_out_of_the_analysis_folder_is_not_downloadable(
    report: dict[str, Any], analysis_dir: Path, tmp_path: Path
) -> None:
    secret = put_file(tmp_path, "secret.txt", b"top secret")
    link = analysis_dir / "files" / DROPPED_SHA256
    link.parent.mkdir()
    link.symlink_to(secret)

    catalog = build_catalog(report, analysis_dir)

    assert catalog.view.dropped[0].downloadable is False
    assert catalog.files == {}


def test_the_pcap_is_the_dump_file_with_the_hash_from_the_report(
    report: dict[str, Any], analysis_dir: Path
) -> None:
    put_file(analysis_dir, "dump.pcap", b"pcap-bytes")

    catalog = build_catalog(report, analysis_dir)

    pcap = catalog.view.pcap
    assert pcap is not None
    assert (pcap.name, pcap.size, pcap.sha256, pcap.downloadable) == (
        "dump.pcap",
        10,
        PCAP_SHA256,
        True,
    )
    assert catalog.files[pcap.id].path == (analysis_dir / "dump.pcap").resolve()
    assert catalog.pcap == (analysis_dir / "dump.pcap").resolve()


def test_there_is_no_pcap_without_the_file(report: dict[str, Any], analysis_dir: Path) -> None:
    catalog = build_catalog(report, analysis_dir)

    assert catalog.view.pcap is None
    assert catalog.pcap is None


def test_the_memory_dump_is_the_file_in_the_analysis_folder(
    report: dict[str, Any], analysis_dir: Path
) -> None:
    put_file(analysis_dir, "memory.dmp", b"0123456789")

    memory = build_catalog(report, analysis_dir).view.memory_dump

    assert memory is not None
    assert (memory.name, memory.size) == ("memory.dmp", 10)


def test_screenshots_are_the_images_of_the_shots_folder_in_order(
    report: dict[str, Any], analysis_dir: Path
) -> None:
    put_file(analysis_dir, "shots/0002.jpg", b"22")
    put_file(analysis_dir, "shots/0001.jpg", b"1")
    put_file(analysis_dir, "shots/0001_small.jpg", b"s")
    put_file(analysis_dir, "shots/notes.txt", b"not an image")

    catalog = build_catalog(report, analysis_dir)

    assert [(s.n, s.name, s.size) for s in catalog.view.screenshots] == [
        (1, "0001.jpg", 1),
        (2, "0002.jpg", 2),
    ]
    assert [path.name for path in catalog.screenshots] == ["0001.jpg", "0002.jpg"]


def test_a_missing_report_gives_empty_collections(analysis_dir: Path) -> None:
    view = build_catalog(None, analysis_dir).view

    assert (view.dropped, view.payloads, view.procdumps, view.configs, view.screenshots) == (
        [],
        [],
        [],
        [],
        [],
    )
    assert (view.memory_dump, view.pcap) == (None, None)


def test_no_analysis_folder_gives_empty_collections(report: dict[str, Any]) -> None:
    view = build_catalog(report, None).view

    assert view.pcap is None
    assert view.screenshots == []
    assert all(not a.downloadable for a in view.dropped)


def test_malformed_report_sections_are_ignored(analysis_dir: Path) -> None:
    broken = {"info": {}, "dropped": "oops", "CAPE": [1], "procdump": [None, 3], "procmemory": 7}

    view = build_catalog(broken, analysis_dir).view

    assert (view.dropped, view.payloads, view.procdumps, view.configs) == ([], [], [], [])


def test_the_download_name_is_a_plain_file_name() -> None:
    assert download_name('..\\..\\evil"\r\nname.exe') == "evil___name.exe"
    assert download_name('we"ird\r\nname') == "we_ird__name"
    assert download_name("") == "sample"
