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

This repository was created as an empty repository and is being initialized from the engineering baseline. Features are not considered complete until implemented and tested against PostgreSQL.

## Planned stack

- Python 3.12+
- FastAPI
- Pydantic v2
- SQLAlchemy 2 async
- PostgreSQL
- S3-compatible object storage
- FFmpeg worker

## Development

The first backend slice will establish the versioning domain, persistence model, API contracts, and PostgreSQL integration tests. See `docs/engineering/REVISION_HISTORY.md` for the design and acceptance criteria.
