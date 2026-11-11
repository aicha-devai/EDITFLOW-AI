"""Restore an encrypted, verified PostgreSQL backup to an isolated restore database.

Requires an age identity file. The target database name must contain 'restore' or
'drill'; the restore is destructive to objects in that target.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
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
    parser.add_argument("--identity-file", default=os.environ.get("AGE_IDENTITY_FILE"))
    parser.add_argument("--allow-overwrite", action="store_true", help="Required: restore drops/replaces objects in the target database")
    args = parser.parse_args()

    if not args.allow_overwrite:
        parser.error("Refusing destructive restore without --allow-overwrite")
    if not args.target_database_url:
        parser.error("Set RESTORE_DATABASE_URL to a dedicated, isolated restore database")
    if not args.identity_file or not Path(args.identity_file).is_file():
        parser.error("Set AGE_IDENTITY_FILE to the protected age identity file")
    if not args.archive.is_file():
        parser.error("Encrypted backup archive does not exist")
    for binary in ("age", "pg_restore"):
        if not shutil.which(binary):
            parser.error(f"{binary} is required on PATH")

    try:
        env = connection_environment(args.target_database_url)
    except ValueError as exc:
        parser.error(str(exc))
    metadata_path = args.archive.with_suffix("").with_suffix(".json")
    if not metadata_path.is_file():
        parser.error("Backup metadata/checksum file is missing")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("encrypted") is not True or metadata.get("verified") is not True:
        parser.error("Backup metadata does not mark an encrypted, verified archive")
    if sha256_file(args.archive) != metadata.get("sha256"):
        parser.error("Encrypted backup checksum is invalid")

    fd, temporary_name = tempfile.mkstemp(prefix="editflow-restore-", suffix=".dump")
    os.close(fd)
    plaintext = Path(temporary_name)
    try:
        os.chmod(plaintext, 0o600)
        subprocess.run([
            "age", "--decrypt", "--identity", args.identity_file,
            "--output", str(plaintext), str(args.archive),
        ], check=True)
        subprocess.run(["pg_restore", "--list", str(plaintext)], check=True, capture_output=True, text=True)
        subprocess.run([
            "pg_restore", "--clean", "--if-exists", "--no-owner", "--no-acl",
            "--exit-on-error", "--dbname", env["PGDATABASE"], str(plaintext),
        ], env=env, check=True)
        print(json.dumps({"restored": True, "archive": str(args.archive), "checksum_verified": True, "decrypted": True, "target_database": env["PGDATABASE"]}))
    finally:
        plaintext.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
