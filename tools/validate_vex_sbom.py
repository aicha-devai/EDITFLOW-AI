#!/usr/bin/env python3
"""Validate that every OpenVEX product PURL exists in the supplied CycloneDX SBOMs."""
from __future__ import annotations

import json
import sys
from pathlib import Path


def load_json(path: str) -> dict:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Unable to read JSON file {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit(f"Expected a JSON object in {path}")
    return value


def main() -> int:
    if len(sys.argv) < 3:
        raise SystemExit(
            "Usage: validate_vex_sbom.py VEX.json SBOM1.cdx.json [SBOM2.cdx.json ...]"
        )

    vex_path, *sbom_paths = sys.argv[1:]
    vex = load_json(vex_path)
    sbom_purls: set[str] = set()

    for path in sbom_paths:
        sbom = load_json(path)
        components = sbom.get("components")
        if not isinstance(components, list):
            raise SystemExit(f"{path}: CycloneDX components array is missing")
        for component in components:
            if isinstance(component, dict) and isinstance(component.get("purl"), str):
                sbom_purls.add(component["purl"])

    statements = vex.get("statements")
    if not isinstance(statements, list):
        raise SystemExit(f"{vex_path}: OpenVEX statements array is missing")

    missing: list[str] = []
    seen: set[tuple[str, str]] = set()
    duplicate_pairs: list[str] = []
    product_count = 0

    for index, statement in enumerate(statements):
        if not isinstance(statement, dict):
            raise SystemExit(f"{vex_path}: statement {index} is not an object")
        cve = statement.get("vulnerability", {}).get("name")
        products = statement.get("products")
        if not isinstance(cve, str) or not isinstance(products, list) or not products:
            raise SystemExit(f"{vex_path}: statement {index} has no vulnerability or products")
        for product in products:
            purl = product.get("@id") if isinstance(product, dict) else None
            if not isinstance(purl, str) or not purl.startswith("pkg:"):
                raise SystemExit(f"{vex_path}: statement {index} has an invalid product PURL")
            product_count += 1
            if purl not in sbom_purls:
                missing.append(f"{cve}: {purl}")
            pair = (cve, purl)
            if pair in seen:
                duplicate_pairs.append(f"{cve}: {purl}")
            seen.add(pair)

    if missing or duplicate_pairs:
        if missing:
            print("OpenVEX products absent from supplied SBOMs:", file=sys.stderr)
            for item in missing:
                print(f"  - {item}", file=sys.stderr)
        if duplicate_pairs:
            print("Duplicate vulnerability/product statements:", file=sys.stderr)
            for item in duplicate_pairs:
                print(f"  - {item}", file=sys.stderr)
        return 1

    print(
        f"OpenVEX/SBOM alignment passed: {len(statements)} statements, "
        f"{product_count} product references, {len(sbom_purls)} SBOM PURLs."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
