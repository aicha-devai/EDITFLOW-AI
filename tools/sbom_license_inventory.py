#!/usr/bin/env python3
"""Export declared component license metadata from a CycloneDX JSON SBOM.

This is an inventory aid, not a legal conclusion: missing metadata must be
resolved against the upstream package and the exact binary/build distribution.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any


def license_labels(component: dict[str, Any]) -> list[str]:
    labels: set[str] = set()
    for item in component.get("licenses") or []:
        if not isinstance(item, dict):
            continue
        if isinstance(item.get("expression"), str):
            labels.add(item["expression"])
        license_data = item.get("license")
        if isinstance(license_data, dict):
            label = license_data.get("id") or license_data.get("name") or license_data.get("url")
            if isinstance(label, str) and label.strip():
                labels.add(label.strip())
    return sorted(labels)


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("usage: sbom_license_inventory.py SBOM.json OUTPUT.csv")
    source, destination = map(Path, sys.argv[1:])
    bom = json.loads(source.read_text(encoding="utf-8"))
    components = bom.get("components")
    if not isinstance(components, list):
        raise SystemExit("CycloneDX document has no components array")

    destination.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for component in components:
        if not isinstance(component, dict):
            continue
        component_type = component.get("type", "")
        # Syft also emits thousands of file-level components. They are useful
        # provenance evidence but are not independently installable packages.
        # Exclude them, and discard binary-signature false positives without a
        # package URL (for example pip's bundled Windows launcher executables).
        if component_type == "file":
            continue
        if component_type == "application" and not component.get("purl"):
            continue
        if component_type not in {"library", "application", "operating-system"}:
            continue
        licenses = license_labels(component)
        rows.append({
            "name": component.get("name", ""),
            "version": component.get("version", ""),
            "type": component.get("type", ""),
            "purl": component.get("purl", ""),
            "declared_licenses": " OR ".join(licenses),
            "license_metadata_status": "declared" if licenses else "review_required",
        })
    rows.sort(key=lambda row: (row["type"], row["name"].lower(), row["version"]))
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else [
            "name", "version", "type", "purl", "declared_licenses", "license_metadata_status"
        ])
        writer.writeheader()
        writer.writerows(rows)
    missing = sum(row["license_metadata_status"] == "review_required" for row in rows)
    print(f"SBOM components: {len(rows)}; components requiring license metadata review: {missing}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
