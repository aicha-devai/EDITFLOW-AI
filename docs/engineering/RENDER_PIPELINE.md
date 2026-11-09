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

## Worker and media pipeline

The dedicated `app.worker_main` process polls and claims jobs in a short transaction, then renders outside the claim transaction. It reads only the pinned snapshot, resolves project-owned assets, probes source media with `ffprobe`, validates source ranges, plans an FFmpeg command, executes it without a shell, and stores the resulting MP4.

The FFmpeg planner currently supports:
- Multiple video clips composited over a black sequence canvas at their timeline positions.
- Source in/out trimming, frame-rate normalization, scale-to-fit with letterboxing, and H.264 output.
- Optional audio mixing when a worker's media probe confirms which inputs contain audio.
- Strict dimension, timing, encoder-profile, and asset-resolution validation.

Custom transforms, transitions, subtitles, still-image clips, and multiple independent audio tracks are not yet supported.

## Storage adapters

- `LocalObjectStorage`: traversal-safe local filesystem adapter for development and Docker Compose.
- `S3ObjectStorage`: S3-compatible adapter for AWS S3, MinIO, and compatible endpoints. It supports worker-side downloads, output uploads, and expiring presigned GET URLs. Credentials are loaded from environment/runtime configuration; do not commit secrets.
- Select with `EDITFLOW_STORAGE_BACKEND=local|s3`. For S3 configure `S3_BUCKET`, `S3_REGION`, optional `S3_ENDPOINT_URL`, and credentials (or use the runtime's IAM role).

The S3 adapter has unit tests with a deterministic fake client. Live bucket connectivity, IAM policy, lifecycle/retention, and production credentials have not been validated in this repository's CI.

## Verification

GitHub Actions installs FFmpeg/ffprobe and runs PostgreSQL and media integration tests. Current suite includes:
1. Immutable timeline pinning and restore/version concurrency tests.
2. Render job idempotency, worker queue claiming, and DB-level snapshot immutability.
3. Worker orchestration against a mocked executor.
4. A real FFmpeg integration test that generates synthetic video+audio, runs the actual planner/executor, probes the MP4, and asserts H.264, audio, duration, and dimensions.
5. Local storage traversal and round-trip tests.
6. S3 adapter contract tests using a fake client.

## Not yet implemented

- Distributed queue telemetry and frame-accurate FFmpeg progress.
- Production object storage bucket provisioning, IAM policy, signed URL API exposure, and live cloud integration test.
- Workspace RBAC; render endpoints must not be exposed publicly before authorization is added.
- Full frontend/editor interface.


## Worker reliability

Migration `0003_render_reliability` adds:
- A unique lease token and expiry timestamp per active attempt.
- Heartbeat timestamps and worker-side lease renewal in a separate database session.
- Attempt counters with a bounded retry policy (default maximum: 3 attempts).
- Delayed retry scheduling with exponential backoff (capped at five minutes).
- Monotonic progress percentage and cancellation requests.
- Recovery of expired worker leases; an expired attempt can be reclaimed by another worker, while exhausted jobs are closed as failed.
- Fencing: heartbeat, completion, and failure operations require the current lease token. A stale worker cannot complete or fail a job after another worker has reclaimed it.
- Attempt-specific output object keys prevent a stale attempt from overwriting a later attempt's output.

The worker lease duration is configured with `RENDER_LEASE_SECONDS` (default 120 seconds; minimum 15). The worker renews the lease independently while rendering. Cancellation of a running job is cooperative: the worker acknowledges it at its next heartbeat/completion boundary; the current FFmpeg process is not yet interrupted mid-encode. Progress is reported at pipeline stages (asset preparation, probing, encode completion, and output upload), not as frame-accurate FFmpeg progress.

API:
- `POST /v1/projects/{project_id}/renders/{job_id}/cancel`
- `GET /v1/projects/{project_id}/renders/{job_id}` includes attempts, max_attempts, progress_percent, and cancel_requested.

Tests cover lease expiry/reclaim, stale-token fencing, retry scheduling, heartbeat renewal, monotonic progress, and queued/running cancellation. Live multi-process crash/restart testing remains a deployment-level verification item.
\n\n## Output Integrity Control\n\nA render is not publishable merely because FFmpeg exits with code zero. Before uploading the result or transitioning a job to `succeeded`, the worker runs `ffprobe` against the encoded file and validates:\n- The file exists, is readable, and is non-empty.\n- The container identifies as MP4.\n- A video stream exists and uses H.264.\n- Width and height exactly match the immutable render plan.\n- Audio presence matches the plan; when audio is expected it must be AAC.\n- Duration is within `max(0.35s, 2/fps)` of the planned duration.\n\nAny mismatch fails closed: the output is not uploaded, no output object key is published, and the render attempt follows the existing retry policy. `ffprobe` parse/decode errors are treated as integrity failures. After metadata validation, the worker runs a separate full decode-only FFmpeg pass (`-v error -xerror -err_detect explode`) over every video and audio stream, mapping them to the null muxer. This reads the complete output without re-encoding; decoder errors, corrupt packets/frames, non-zero exit, timeout, or cancellation prevent publication. The scan is bounded by the render timeout and runs before upload. It is a technical decode-integrity check, not a perceptual quality assessment (e.g. black-frame, freeze, visual artifact, or audio clipping detection).\n