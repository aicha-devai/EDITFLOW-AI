"""Single-job worker orchestration for local storage and FFmpeg.

The queue claim must be committed before this function is called. Pass a fresh
AsyncSession for status updates; never hold the claim transaction open while
running a long media process.
"""
from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.media_probe import MediaProbeError, probe_media
from app.models import Asset, RenderJob
from app.render_engine import build_ffmpeg_plan
from app.render_executor import execute_ffmpeg_plan
from app.rendering import complete_render_job, fail_render_job, heartbeat_render_job, LeaseLost, RenderCancelled
from app.storage import LocalObjectStorage


class RenderWorkerError(RuntimeError):
    pass


async def _report_progress(session_factory, job_id: UUID, lease_token: UUID, progress: int) -> None:
    if session_factory is None:
        return
    async with session_factory() as progress_session:
        async with progress_session.begin():
            await heartbeat_render_job(
                progress_session, job_id, lease_token,
                lease_seconds=120, progress_percent=progress,
            )


async def render_claimed_job(
    session: AsyncSession,
    job_id: UUID,
    storage: LocalObjectStorage,
    work_root: str | Path,
    timeout_seconds: int = 3600,
    lease_token: UUID | None = None,
    session_factory=None,
) -> RenderJob:
    """Resolve pinned assets, probe, render and store one already-claimed job."""
    job = await session.scalar(select(RenderJob).where(RenderJob.id == job_id))
    if job is None:
        raise LookupError("Render job does not exist")
    if job.status != "running":
        raise RenderWorkerError(f"Job must be running, got {job.status}")

    lease_token = lease_token or job.lease_token
    if lease_token is None or job.lease_token != lease_token:
        raise LeaseLost("Render worker has no valid lease token")
    snapshot = job.timeline_snapshot
    clips = list(snapshot.get("clips") or [])
    if not clips:
        await fail_render_job(session, job_id, "Timeline contains no clips", lease_token)
        return job

    try:
        asset_ids = {UUID(str(clip["asset_id"])) for clip in clips}
    except (KeyError, ValueError, TypeError) as exc:
        await fail_render_job(session, job_id, f"Invalid clip asset reference: {exc}", lease_token)
        return job

    assets = (await session.scalars(
        select(Asset).where(
            Asset.project_id == job.project_id,
            Asset.id.in_(asset_ids),
        )
    )).all()
    asset_by_id = {asset.id: asset for asset in assets}
    missing = asset_ids - set(asset_by_id)
    if missing:
        await fail_render_job(session, job_id, "Timeline references missing or foreign-project assets", lease_token)
        return job

    root = Path(work_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    try:
        await _report_progress(session_factory, job_id, lease_token, 10)
        with tempfile.TemporaryDirectory(prefix=f"editflow-{job_id}-", dir=root) as temp_dir:
            temp = Path(temp_dir)
            asset_paths: dict[str, str] = {}
            media_audio: dict[str, bool] = {}
            media_duration: dict[str, float] = {}
            for asset_id in asset_ids:
                asset = asset_by_id[asset_id]
                local_path = await asyncio.to_thread(
                    storage.materialize,
                    asset.object_key,
                    temp / f"{asset_id}.media",
                )
                info = await probe_media(str(local_path))
                asset_paths[str(asset_id)] = str(local_path)
                media_audio[str(asset_id)] = info.has_audio
                media_duration[str(asset_id)] = info.duration_seconds
                await _report_progress(session_factory, job_id, lease_token, 15 + int(35 * len(asset_paths) / max(1, len(asset_ids))))

            for index, clip in enumerate(clips):
                asset_id = str(UUID(str(clip["asset_id"])))
                source_out = float(clip.get("source_out", 0))
                source_in = float(clip.get("source_in", 0))
                if source_out <= source_in:
                    raise RenderWorkerError(f"Clip {index} source_out must be greater than source_in")
                if source_out > media_duration[asset_id] + 0.05:
                    raise RenderWorkerError(f"Clip {index} source_out exceeds media duration")

            await _report_progress(session_factory, job_id, lease_token, 60)
            output_path = temp / "render.mp4"
            plan = build_ffmpeg_plan(
                snapshot,
                asset_paths,
                str(output_path),
                render_profile=job.render_profile,
                asset_has_audio=media_audio,
            )
            await execute_ffmpeg_plan(plan, timeout_seconds=timeout_seconds)
            await _report_progress(session_factory, job_id, lease_token, 90)
            object_key = f"renders/{job.project_id}/{job.id}/attempt-{job.attempts}.mp4"
            await asyncio.to_thread(storage.put_file, output_path, object_key)
            await _report_progress(session_factory, job_id, lease_token, 95)
            return await complete_render_job(session, job_id, object_key, lease_token)
    except (LeaseLost, RenderCancelled):
        raise
    except Exception as exc:
        await fail_render_job(session, job_id, str(exc) or exc.__class__.__name__, lease_token)
        return await session.scalar(select(RenderJob).where(RenderJob.id == job_id))
