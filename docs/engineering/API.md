# Initial API Contract

Base path: `/v1`

## Create a project

`POST /v1/projects`

```json
{"title":"My faceless documentary"}
```

Returns a project UUID.

## Save a timeline snapshot

`POST /v1/projects/{project_id}/timeline`

```json
{
  "expected_version": 0,
  "idempotency_key": "client-generated-request-id",
  "message": "First rough cut",
  "timeline": {
    "schema_version": "0.1",
    "project_id": "PROJECT_UUID",
    "version": 0,
    "sequence": {"width": 1080, "height": 1920, "fps": 30},
    "clips": [],
    "editorial_notes": []
  }
}
```

For an existing timeline, `expected_version` is required. A stale expected version returns HTTP 409. Replaying an idempotency key with the same content returns the original revision; reusing it with different content returns HTTP 409. An unchanged latest timeline is a no-op.

## List revisions

`GET /v1/projects/{project_id}/versions`

Returns immutable snapshots in ascending version order, including parent and restore provenance.

## Compare revisions

`GET /v1/projects/{project_id}/versions/compare?from_version=1&to_version=2`

Returns clip additions, removals, changed clip fields, sequence-setting changes, and whether editorial notes changed.

## Restore a revision

`POST /v1/projects/{project_id}/versions/{source_version}/restore`

```json
{"expected_version": 2, "message": "Restore approved cut"}
```

Restoration appends a new revision and records the source revision UUID. It does not move the history pointer backward or delete newer revisions.

## Local startup

```bash
docker compose up --build
```

The API listens on `http://localhost:8000`; health check: `GET /health`.

The development startup creates missing tables automatically. Production deployment must use reviewed Alembic migrations and enforce workspace membership authorization before exposing project endpoints.
