# Render Pipeline — immutable timeline pinning

## Design invariant

A render job is a durable request to render one exact timeline revision. It is never a pointer to the mutable project head.

At creation, the API resolves either the requested project version or the current version under a project-row lock. It persists:
- `timeline_version_id`: FK to the immutable revision, with `ON DELETE RESTRICT`
- `timeline_snapshot`: deep-copied JSON document for worker input
- `timeline_hash`: canonical SHA-256 matching the saved revision
- `render_profile`: immutable-by-convention render settings
- lifecycle state, timestamps, output key, and error details

A PostgreSQL trigger rejects updates to `project_id`, `timeline_version_id`, `timeline_snapshot`, or `timeline_hash`. Status/output metadata remains mutable for the worker lifecycle.

## Lifecycle

`queued → running → succeeded | failed`

Workers claim the oldest queued row with `SELECT ... FOR UPDATE SKIP LOCKED` inside a transaction. Multiple workers can poll without claiming the same row. Before transitioning to running, the service recomputes the canonical timeline hash and fails closed if it differs.

The worker receives the pinned snapshot. It must not read `projects.current_version_id` to determine its edit. Completion records an output object key; failure records a bounded error message.

## API

- `POST /v1/projects/{project_id}/renders`: create job, optionally pin a specific timeline version.
- `GET /v1/projects/{project_id}/renders/{job_id}`: inspect job status and pinned revision.

Creation supports a project-scoped `request_key` for safe retries.

## Verification

PostgreSQL integration tests cover:
1. Create a job pinned to version 1.
2. Save version 2 with different sequence settings and notes.
3. Assert the job still references version 1 and its snapshot/hash are unchanged.
4. Claim the job and assert worker input still contains version 1.
5. Complete the job and verify output metadata.
6. Attempt to mutate the pinned hash and assert the database trigger rejects it.
7. Concurrent queue consumers use row locking with `SKIP LOCKED`.

## Not yet implemented

- FFmpeg command planner/executor and media probing.
- Object-storage upload/download adapter and signed URLs.
- Progress events, cancellation, retries/lease expiry, and distributed queue telemetry.
- Workspace RBAC; render endpoints must not be exposed publicly before authorization is added.
