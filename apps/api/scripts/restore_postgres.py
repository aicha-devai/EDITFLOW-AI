"""Restore a verified custom-format backup to an explicitly named restore database.

This is destructive to objects in the target database. The target database name must
contain 'restore' or 'drill'. Never point this command at the live production database.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit


def connection_environment(database_url: str) -> dict[str, str]:
    parsed = urlsplit(database_url.replace("postgresql+asyncpg://", "postgresql://", 1))
    database_name = unquote(parsed.path.lstrip("/"))
    if not parsed.hostname or not database_name:
        raise ValueError("Restore URL must include a database host and name")
    if "restore" not in database_name.lower() and "drill" not in database_name.lower():
        raise ValueError("Refusing restore: target database name must include 'restore' or 'drill'")
    query = parse_qs(parsed.query)
    env = os.environ.copy()
    env.update({
        "PGHOST": parsed.hostname,
        "PGPORT": str(parsed.port or 5432),
        "PGDATABASE": database_name,
        "PGSSLMODE": (query.get("sslmode") or query.get("ssl") or ["require"])[0],
    })
    if parsed.username:
        env["PGUSER"] = unquote(parsed.username)
    if parsed.password:
        env["PGPASSWORD"] = unquote(parsed.password)
    return env


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
    if not shutil.which("pg_restore"):
        parser.error("pg_restore is required on PATH")

    try:
        env = connection_environment(args.target_database_url)
    except ValueError as exc:
        parser.error(str(exc))
    metadata_path = args.archive.with_suffix(".json")
    if not metadata_path.is_file():
        parser.error("Backup metadata/checksum file is missing")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if sha256_file(args.archive) != metadata.get("sha256") or metadata.get("verified") is not True:
        parser.error("Backup checksum or verification metadata is invalid")

    subprocess.run(["pg_restore", "--list", str(args.archive)], check=True, capture_output=True, text=True)
    subprocess.run([
        "pg_restore", "--clean", "--if-exists", "--no-owner", "--no-acl",
        "--exit-on-error", "--dbname", env["PGDATABASE"], str(args.archive),
    ], env=env, check=True)
    print(json.dumps({"restored": True, "archive": str(args.archive), "checksum_verified": True, "target_database": env["PGDATABASE"]}))


if __name__ == "__main__":
    main()
