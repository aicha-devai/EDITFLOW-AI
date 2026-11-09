"""Polling worker entry point: python -m app.worker_main."""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.rendering import claim_next_render_job, heartbeat_render_job, LeaseLost, RenderCancelled
from app.render_worker import render_claimed_job
from app.storage import create_object_storage


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("editflow.worker")


async def _maintain_lease(sessions, job_id, lease_token, lease_seconds: int) -> None:
    interval = max(2, lease_seconds // 3)
    progress = 5
    while True:
        await asyncio.sleep(interval)
        async with sessions() as session:
            async with session.begin():
                await heartbeat_render_job(
                    session, job_id, lease_token, lease_seconds=lease_seconds,
                    progress_percent=progress,
                )
        logger.debug("Heartbeat renewed for job %s", job_id)


async def _run_with_lease(render_coro, heartbeat_coro):
    """Keep rendering supervised; lease loss/cancellation stops the encode task."""
    render_task = asyncio.create_task(render_coro)
    heartbeat_task = asyncio.create_task(heartbeat_coro)
    try:
        done, _ = await asyncio.wait(
            {render_task, heartbeat_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if heartbeat_task in done:
            try:
                await heartbeat_task
            except BaseException:
                render_task.cancel()
                await asyncio.gather(render_task, return_exceptions=True)
                raise
            raise RuntimeError("Render lease heartbeat exited unexpectedly")
        return await render_task
    finally:
        for task in (render_task, heartbeat_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(render_task, heartbeat_task, return_exceptions=True)


async def run_worker() -> None:
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    work_root = Path(os.getenv("EDITFLOW_WORK_ROOT", "/tmp/editflow-work"))
    poll_seconds = float(os.getenv("WORKER_POLL_SECONDS", "2"))
    timeout_seconds = int(os.getenv("RENDER_TIMEOUT_SECONDS", "3600"))
    lease_seconds = int(os.getenv("RENDER_LEASE_SECONDS", "120"))
    if lease_seconds < 15:
        raise ValueError("RENDER_LEASE_SECONDS must be at least 15")
    storage = create_object_storage(settings)
    work_root.mkdir(parents=True, exist_ok=True)

    logger.info("Render worker started; storage backend=%s lease=%ss", settings.storage_backend, lease_seconds)
    try:
        while True:
            job_id = None
            lease_token = None
            async with sessions() as session:
                async with session.begin():
                    job = await claim_next_render_job(session, lease_seconds=lease_seconds)
                    if job is not None and job.status == "running":
                        job_id = job.id
                        lease_token = job.lease_token
                    elif job is not None:
                        logger.error("Job %s closed during claim validation: %s", job.id, job.status)

            if job_id is None:
                await asyncio.sleep(poll_seconds)
                continue

            logger.info("Rendering job %s attempt lease acquired", job_id)

            async def render():
                async with sessions() as session:
                    async with session.begin():
                        result = await render_claimed_job(
                            session, job_id, storage, work_root,
                            timeout_seconds=timeout_seconds, lease_token=lease_token,
                            session_factory=sessions,
                        )
                        logger.info(
                            "Job %s finished status=%s progress=%s",
                            job_id, result.status, result.progress_percent,
                        )
                        return result

            try:
                await _run_with_lease(
                    render(),
                    _maintain_lease(sessions, job_id, lease_token, lease_seconds),
                )
            except (LeaseLost, RenderCancelled) as exc:
                logger.warning("Job %s worker lease/cancellation ended: %s", job_id, exc)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        logger.info("Render worker stopped")
