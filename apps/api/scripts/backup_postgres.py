"""Create a PostgreSQL custom-format backup and verify its archive/checksum.

Requires DATABASE_URL and pg_dump/pg_restore on PATH. Store the resulting backup and
metadata in encrypted, access-controlled off-host storage with a retention policy.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def run(command: list[str]) -> str:
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    return completed.stdout


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="backups")
    args = parser.parse_args()
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        parser.error("DATABASE_URL must be supplied through the environment/secret manager")
    for binary in ("pg_dump", "pg_restore"):
        if not shutil.which(binary):
            parser.error(f"{binary} is required on PATH")

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive = output_dir / f"editflow-{stamp}.dump"
    metadata = archive.with_suffix(".json")

    try:
        run(["pg_dump", "--format=custom", "--no-owner", "--no-acl", "--file", str(archive), database_url])
        run(["pg_restore", "--list", str(archive)])
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        metadata.write_text(json.dumps({
            "created_at": stamp,
            "format": "postgres-custom",
            "archive": archive.name,
            "sha256": digest,
            "verified": True,
        }, indent=2) + "\\n", encoding="utf-8")
        print(json.dumps({"archive": str(archive), "metadata": str(metadata), "sha256": digest, "verified": True}))
    except Exception:
        archive.unlink(missing_ok=True)
        metadata.unlink(missing_ok=True)
        raise


if __name__ == "__main__":
    main()
