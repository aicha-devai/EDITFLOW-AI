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
