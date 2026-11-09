# Timeline Revision History — Engineering Contract

## Guarantees targeted by this implementation

1. First save creates version 1.
2. A changed canonical timeline creates the next monotonically increasing version.
3. An unchanged canonical timeline is a no-op.
4. Version listing is ascending and stable.
5. Restored revisions record `restored_from_version_id`.
6. Comparison reports added, removed, and changed clips by stable clip UUID.
7. Restore appends a new revision; it never deletes later revisions.
8. Writers supply `expected_version`; stale writes receive HTTP 409.
9. Canonical SHA-256 hashes prevent duplicate snapshots.
10. Version-to-asset reference rows use RESTRICT deletion to protect historical assets.
11. Render jobs must persist a `timeline_version_id` and render only that immutable snapshot (worker integration pending).
12. Version creation, asset references, and current pointer update run in one database transaction.
13. Project authorization/RBAC is not yet implemented and must be added before exposing this API publicly.
14. PostgreSQL tests cover rollback and two independent concurrent writers; CI runs these against PostgreSQL.

## Canonicalization

The client-supplied version field is normalized to zero before hashing. JSON keys are sorted and compactly serialized before SHA-256. The persisted snapshot stores its allocated version number while the content hash remains independent of that number.

## Concurrency

The project row is locked with `SELECT ... FOR UPDATE` before reading the latest revision and allocating the next number. This serializes concurrent writers for the same project. The caller's expected version is checked after the lock is acquired.

## Restore semantics

A restore copies the selected immutable snapshot into a new version. It does not move the project pointer backward and does not delete or rewrite intervening revisions.

## Current implementation limits

- This is the first backend slice, not a complete product.
- Workspace membership/RBAC and render-job pinning remain unimplemented. Alembic migration infrastructure and PostgreSQL integration tests are present; the latest CI run must pass before treating the migration change as verified.
- Run tests against PostgreSQL, not SQLite, because row locking and JSONB behavior are PostgreSQL-specific.
