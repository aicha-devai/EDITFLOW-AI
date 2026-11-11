# EDITFLOW AI

**The AI Creative Editor for Faceless Storytelling**

EDITFLOW AI is a web-first, story-aware editing system for faceless documentary, mystery, history, and narrated-story creators.

## Initial engineering focus

- Timeline documents with stable clip IDs.
- Immutable timeline revision history.
- Content-hash deduplication (no new version for unchanged timelines).
- Optimistic concurrency control to prevent stale writes.
- Restore as a new revision, preserving all later history.
- Version comparison with clip-level change summaries.
- Render jobs pinned to an immutable timeline version, with a database-enforced snapshot/hash lock.
- PostgreSQL worker claiming with `FOR UPDATE SKIP LOCKED` and render lifecycle tracking.
- Asset retention references for historical timelines.

## Repository status

This repository is being built incrementally from the engineering baseline. The current backend slice includes PostgreSQL-backed timeline versioning, immutable history, optimistic concurrency, Alembic migrations, and integration tests. It is not yet production-ready.

## Planned stack

- Python 3.12+
- FastAPI
- Pydantic v2
- SQLAlchemy 2 async
- PostgreSQL
- S3-compatible object storage
- FFmpeg worker

## Development

Run `docker compose up --build` to start PostgreSQL and the API; the container applies Alembic migrations before API startup. See `docs/engineering/REVISION_HISTORY.md` and `docs/engineering/RENDER_PIPELINE.md` for guarantees and remaining gaps.


## Local render worker

The Compose stack includes a dedicated FFmpeg worker:

```bash
docker compose up --build
```

The API container applies database migrations before becoming healthy; the render worker waits for that health check. Both services share the `editflow_storage` volume at `/var/lib/editflow`.

For a local development asset, place the media file at the path represented by its `assets.object_key` under `/var/lib/editflow`. Once a saved Timeline references that project-owned asset and a Render Job is queued, the worker probes it with `ffprobe`, renders the pinned snapshot with FFmpeg, and writes the result to:

`renders/{project_id}/{job_id}.mp4`

This first worker adapter uses local filesystem storage. It is not yet an S3-compatible production storage integration. See [Render Pipeline documentation](docs/engineering/RENDER_PIPELINE.md) for supported timeline features and current limitations.


## Story Graph Explorer

A browser-based interactive graph viewer lives in `apps/web`. It reads the evidence graph persisted by a successful Render Job; it does not mutate the pinned Timeline.

Start the API and database:

```bash
docker compose up --build
```

In another terminal, start the explorer:

```bash
cd apps/web
npm install
npm run dev
```

Open the Vite URL (normally `http://localhost:5173`), enter the Project UUID and successful Render Job UUID, then choose **Load graph**. The API base URL defaults to `http://localhost:8000` and can be changed from the settings control.

The explorer supports:
- Interactive selection of graph nodes and relationship edges.
- Entity-type filters and text search.
- A detail inspector with connected relationships, provenance, timestamps and linked evidence.
- Relationship verification labels and explicit narration-claim warnings for causal edges.
- Graph zoom controls and responsive layout.

The Explorer requires an authenticated account. Project reads are limited to the owner and accepted collaborators; project mutations require owner/editor access. Viewer collaborators have read-only access. For non-local hosting, set `EDITFLOW_CORS_ORIGINS` to the exact HTTPS browser origins. The Compose file is for development only; do not expose its default database credentials or ports as a public production deployment.


### Timestamp-linked video playback

After loading a successful Render Job, the Explorer requests the immutable rendered MP4 from:

`GET /v1/projects/{project_id}/renders/{job_id}/media`

Local storage is streamed through a range-capable API response; S3 storage uses a short-lived presigned redirect. The player uses browser-native seeking and HTTP byte ranges, so clicking a timestamped shot, narration segment, visual observation, story beat, or evidence card jumps to that point in the rendered video. Entity and relationship selections jump to their earliest resolvable evidence timestamp when one exists.

The player does not expose raw storage object keys as public URLs and does not modify the Render Job or Timeline.


The Explorer also shows a horizontally scrollable, timestamp-sorted evidence strip (up to 160 markers). Selecting a marker selects its exact graph node and seeks the player. During playback, the current timestamped evidence is highlighted in both the strip and graph, and the player status identifies the active evidence item. This is a time-overlap cue, not a claim that the evidence semantically verifies the video content.


## Account security and production readiness

- Account registration requires email verification.
- Password reset links are one-time and revoke existing sessions.
- Project invitations are email-bound, expire, and support Editor or Viewer access.
- Access and refresh sessions rotate; refresh-token reuse revokes the session family.
- See [Production Security and Email Readiness](PRODUCTION_SECURITY_AND_EMAIL_READINESS.md) for mandatory deployment checks and remaining launch blockers.
- See [Legacy Project Ownership Recovery](LEGACY_PROJECT_OWNERSHIP.md) for the read-only inventory and audited claim runbook.

**Production status:** not approved for public launch until the production ownership inventory is reconciled, SMTP delivery is verified, browser tokens move to HttpOnly cookies (or an equivalent BFF design), and infrastructure/backup controls are signed off.
