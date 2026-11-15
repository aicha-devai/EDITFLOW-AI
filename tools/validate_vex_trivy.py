#!/usr/bin/env python3
"""Validate OpenVEX product PURLs against Trivy's own package identifiers."""
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
            "Usage: validate_vex_trivy.py VEX.json TRIVY_RAW1.json [TRIVY_RAW2.json ...]"
        )

    vex_path, *report_paths = sys.argv[1:]
    vex = load_json(vex_path)
    trivy_purls: set[str] = set()

    for path in report_paths:
        report = load_json(path)
        results = report.get("Results")
        if not isinstance(results, list):
            raise SystemExit(f"{path}: Trivy Results array is missing")
        for result in results:
            if not isinstance(result, dict):
                continue
            for vulnerability in result.get("Vulnerabilities") or []:
                identifier = vulnerability.get("PkgIdentifier") or {}
                purl = identifier.get("PURL")
                if isinstance(purl, str):
                    trivy_purls.add(purl)

    statements = vex.get("statements")
    if not isinstance(statements, list):
        raise SystemExit(f"{vex_path}: OpenVEX statements array is missing")

    missing: list[str] = []
    seen: set[tuple[str, str]] = set()
    duplicates: list[str] = []
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
            if purl not in trivy_purls:
                missing.append(f"{cve}: {purl}")
            pair = (cve, purl)
            if pair in seen:
                duplicates.append(f"{cve}: {purl}")
            seen.add(pair)

    if missing or duplicates:
        if missing:
            print("OpenVEX products absent from Trivy package identifiers:", file=sys.stderr)
            for item in missing:
                print(f"  - {item}", file=sys.stderr)
        if duplicates:
            print("Duplicate vulnerability/product statements:", file=sys.stderr)
            for item in duplicates:
                print(f"  - {item}", file=sys.stderr)
        return 1

    print(
        f"OpenVEX/Trivy alignment passed: {len(statements)} statements, "
        f"{product_count} product references, {len(trivy_purls)} Trivy PURLs."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
