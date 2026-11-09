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

The container applies Alembic migrations (`alembic upgrade head`) before starting the API. For local development, run `alembic upgrade head` from `apps/api` with `DATABASE_URL` set. The API no longer creates schema implicitly at startup. Workspace membership authorization is still required before public exposure.


## Create a render job

`POST /v1/projects/{project_id}/renders`

```json
{
  "timeline_version": 3,
  "render_profile": {"resolution": "1080x1920", "fps": 30},
  "request_key": "render-request-uuid"
}
```

`timeline_version` is optional. If omitted, the project current version is resolved while the project row is locked. The created job stores the exact `timeline_version_id`, a deep-copied timeline snapshot, and its canonical SHA-256 hash. Later timeline saves do not alter the job input. The database trigger rejects changes to the pinned project, version, snapshot, or hash. A request key makes job creation idempotent.

Returns HTTP 202 with `job_id`, pinned version ID, and snapshot hash.

## Get render status

`GET /v1/projects/{project_id}/renders/{job_id}`

Returns status, pinned version ID/hash, render profile, output object key, and lifecycle timestamps.

## Worker contract

The worker uses `app.rendering.claim_next_render_job` inside a database transaction. It claims the oldest queued job with `FOR UPDATE SKIP LOCKED`, verifies the pinned snapshot hash, and transitions it to `running`. It must render exclusively from `job.timeline_snapshot`; it must never resolve `projects.current_version_id` after claiming. On completion call `complete_render_job`; on failure call `fail_render_job`. Output storage and the FFmpeg execution adapter are separate integration steps.
