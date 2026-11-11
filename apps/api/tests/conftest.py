import os
import sys
from pathlib import Path
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

@pytest_asyncio.fixture
async def db_session():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL must point to a migrated PostgreSQL test database")
    engine = create_async_engine(url)
    # CI applies Alembic migrations before pytest. Preserve the migrated schema and
    # truncate data only, so PostgreSQL triggers and constraints are exercised.
    async with engine.begin() as conn:
        await conn.execute(text(
            "TRUNCATE TABLE rate_limit_buckets, auth_action_tokens, project_invitations, users, render_jobs, timeline_asset_references, "
            "timeline_versions, assets, projects RESTART IDENTITY CASCADE"
        ))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()
