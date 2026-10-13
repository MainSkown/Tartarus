#!/usr/bin/env python3
"""Rebuilds backend/app/data/attack_techniques.json from MITRE's enterprise ATT&CK STIX bundle.

CAPE reports ATT&CK technique ids only; the Detections view needs each id's tactics and name.
Run when a new ATT&CK release should ship:  python3 scripts/build-attack-table.py
"""

import json
import sys
import urllib.request
from pathlib import Path
from typing import Any

SOURCE = (
    "https://raw.githubusercontent.com/mitre-attack/attack-stix-data/master/"
    "enterprise-attack/enterprise-attack.json"
)
OUTPUT = Path(__file__).resolve().parent.parent / "backend/app/data/attack_techniques.json"
KILL_CHAIN = "mitre-attack"
DOWNLOAD_TIMEOUT_SECONDS = 300


def _by_type(bundle: dict[str, Any], object_type: str) -> list[dict[str, Any]]:
    return [item for item in bundle["objects"] if item.get("type") == object_type]


def _tactics_in_matrix_order(bundle: dict[str, Any]) -> list[dict[str, str]]:
    matrices = _by_type(bundle, "x-mitre-matrix")
    if not matrices:
        raise ValueError("the bundle has no ATT&CK matrix to take the tactic order from")
    (matrix,) = matrices
    by_stix_id = {item["id"]: item for item in _by_type(bundle, "x-mitre-tactic")}
    return [
        {"id": by_stix_id[ref]["x_mitre_shortname"], "name": by_stix_id[ref]["name"]}
        for ref in matrix["tactic_refs"]
    ]


def _attack_id(technique: dict[str, Any]) -> str:
    return next(
        reference["external_id"]
        for reference in technique["external_references"]
        if reference["source_name"] == KILL_CHAIN
    )


def _is_current(technique: dict[str, Any]) -> bool:
    return not technique.get("x_mitre_deprecated") and not technique.get("revoked")


def _technique_entry(technique: dict[str, Any], tactic_order: list[str]) -> dict[str, Any]:
    phases = {
        phase["phase_name"]
        for phase in technique.get("kill_chain_phases", [])
        if phase["kill_chain_name"] == KILL_CHAIN
    }
    return {
        "name": technique["name"],
        "tactics": sorted(phases, key=lambda phase: (tactic_order.index(phase), phase)),
    }


def build_table(bundle: dict[str, Any], source: str) -> dict[str, Any]:
    tactics = _tactics_in_matrix_order(bundle)
    tactic_order = [tactic["id"] for tactic in tactics]
    (collection,) = _by_type(bundle, "x-mitre-collection")
    techniques = {
        _attack_id(technique): _technique_entry(technique, tactic_order)
        for technique in _by_type(bundle, "attack-pattern")
        if _is_current(technique)
    }
    return {
        "version": collection["x_mitre_version"],
        "modified": collection["modified"][:10],
        "source": source,
        "tactics": tactics,
        "techniques": dict(sorted(techniques.items())),
    }


def download(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:  # noqa: S310
        bundle: dict[str, Any] = json.load(response)
    return bundle


def main() -> int:
    table = build_table(download(SOURCE), SOURCE)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(table, separators=(",", ":"), ensure_ascii=False) + "\n")
    print(  # noqa: T201
        f"ATT&CK {table['version']} ({table['modified']}): "
        f"{len(table['techniques'])} techniques -> {OUTPUT}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
