"""Restore a verified custom-format backup to an explicitly named target database.

This is destructive to objects in the target database. Use a fresh isolated restore
database for drills; never point it at the live production database.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--target-database-url", default=os.environ.get("RESTORE_DATABASE_URL"))
    parser.add_argument("--allow-overwrite", action="store_true", help="Required: restore drops/replaces objects in the target database")
    args = parser.parse_args()

    if not args.allow_overwrite:
        parser.error("Refusing destructive restore without --allow-overwrite")
    if not args.target_database_url:
        parser.error("Set RESTORE_DATABASE_URL to a dedicated, isolated restore database")
    if not args.archive.is_file():
        parser.error("Backup archive does not exist")
    for binary in ("pg_restore",):
        if not shutil.which(binary):
            parser.error(f"{binary} is required on PATH")

    metadata_path = args.archive.with_suffix(".json")
    if not metadata_path.is_file():
        parser.error("Backup metadata/checksum file is missing")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    actual = hashlib.sha256(args.archive.read_bytes()).hexdigest()
    if actual != metadata.get("sha256") or metadata.get("verified") is not True:
        parser.error("Backup checksum or verification metadata is invalid")

    subprocess.run(["pg_restore", "--list", str(args.archive)], check=True, capture_output=True, text=True)
    subprocess.run([
        "pg_restore", "--clean", "--if-exists", "--no-owner", "--no-acl",
        "--exit-on-error", "--dbname", args.target_database_url, str(args.archive),
    ], check=True)
    print(json.dumps({"restored": True, "archive": str(args.archive), "checksum_verified": True, "target": "explicit restore database"}))


if __name__ == "__main__":
    main()
