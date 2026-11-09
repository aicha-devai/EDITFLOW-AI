"""Polling worker entry point: python -m app.worker_main."""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.rendering import claim_next_render_job
from app.render_worker import render_claimed_job
from app.storage import LocalObjectStorage


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("editflow.worker")


async def run_worker() -> None:
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    storage_root = Path(os.getenv("EDITFLOW_STORAGE_ROOT", "/var/lib/editflow"))
    work_root = Path(os.getenv("EDITFLOW_WORK_ROOT", "/tmp/editflow-work"))
    poll_seconds = float(os.getenv("WORKER_POLL_SECONDS", "2"))
    timeout_seconds = int(os.getenv("RENDER_TIMEOUT_SECONDS", "3600"))
    storage = LocalObjectStorage(storage_root)
    work_root.mkdir(parents=True, exist_ok=True)

    logger.info("Render worker started; storage root=%s", storage_root)
    try:
        while True:
            job_id = None
            async with sessions() as session:
                async with session.begin():
                    job = await claim_next_render_job(session)
                    if job is not None and job.status == "running":
                        job_id = job.id
                    elif job is not None:
                        logger.error("Job %s failed pinned snapshot validation", job.id)

            if job_id is None:
                await asyncio.sleep(poll_seconds)
                continue

            logger.info("Rendering job %s", job_id)
            async with sessions() as session:
                async with session.begin():
                    result = await render_claimed_job(
                        session,
                        job_id,
                        storage,
                        work_root,
                        timeout_seconds=timeout_seconds,
                    )
                    logger.info("Job %s finished with status=%s", job_id, result.status)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        logger.info("Render worker stopped")
