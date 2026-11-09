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
- Render jobs pinned to an immutable timeline version.
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

Run `docker compose up --build` to start PostgreSQL and the API; the container applies Alembic migrations before API startup. See `docs/engineering/REVISION_HISTORY.md` for guarantees and remaining gaps.
