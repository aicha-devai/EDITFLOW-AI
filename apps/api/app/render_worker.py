"""Single-job worker orchestration with fail-closed output integrity checks."""
from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.evidence_extraction import EvidenceExtractionError, extract_render_evidence
from app.story_analysis import analyze_story_sequence
from app.story_continuity import build_story_continuity_graph
from app.media_probe import probe_media
from app.models import Asset, RenderJob
from app.render_engine import build_ffmpeg_plan
from app.render_executor import execute_ffmpeg_plan, verify_output_decode
from app.output_integrity import validate_render_output
from app.perceptual_qc import analyze_render_quality
from app.rendering import complete_render_job, fail_render_job, heartbeat_render_job, LeaseLost, RenderCancelled
from app.storage import LocalObjectStorage


class RenderWorkerError(RuntimeError):
    pass


async def _report_progress(session_factory, job_id: UUID, lease_token: UUID, progress: int) -> None:
    if session_factory is None:
        return
    async with session_factory() as progress_session:
        async with progress_session.begin():
            await heartbeat_render_job(progress_session, job_id, lease_token,
                                        lease_seconds=120, progress_percent=progress)


def _attach_signal_observations(evidence: dict, findings: list[dict]) -> None:
    """Turn measured, timestamped signal findings into explicit audio evidence."""
    observations = evidence.setdefault("audio_observations", [])
    for finding in findings:
        if finding.get("code") != "audio_silence":
            continue
        start, end = finding.get("start_seconds"), finding.get("end_seconds")
        if start is None or end is None:
            continue
        observations.append({
            "start_seconds": float(start), "end_seconds": float(end),
            "description": "FFmpeg signal analysis detected sustained audio silence in this interval.",
            "source": "ffmpeg.silencedetect",
        })


async def render_claimed_job(
    session: AsyncSession, job_id: UUID, storage: LocalObjectStorage,
    work_root: str | Path, timeout_seconds: int = 3600,
    lease_token: UUID | None = None, session_factory=None,
) -> RenderJob:
    """Resolve pinned assets, render, verify, extract evidence, then publish."""
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
    assets = (await session.scalars(select(Asset).where(
        Asset.project_id == job.project_id, Asset.id.in_(asset_ids)
    ))).all()
    asset_by_id = {asset.id: asset for asset in assets}
    if asset_ids - set(asset_by_id):
        await fail_render_job(session, job_id, "Timeline references missing or foreign-project assets", lease_token)
        return job

    root = Path(work_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    try:
        await _report_progress(session_factory, job_id, lease_token, 10)
        with tempfile.TemporaryDirectory(prefix=f"editflow-{job_id}-", dir=root) as temp_dir:
            temp = Path(temp_dir)
            asset_paths, media_audio, media_duration = {}, {}, {}
            for asset_id in asset_ids:
                asset = asset_by_id[asset_id]
                local_path = await asyncio.to_thread(storage.materialize, asset.object_key, temp / f"{asset_id}.media")
                info = await probe_media(str(local_path))
                asset_paths[str(asset_id)] = str(local_path)
                media_audio[str(asset_id)] = info.has_audio
                media_duration[str(asset_id)] = info.duration_seconds
                await _report_progress(session_factory, job_id, lease_token,
                                       15 + int(35 * len(asset_paths) / max(1, len(asset_ids))))
            for index, clip in enumerate(clips):
                asset_id = str(UUID(str(clip["asset_id"])))
                source_out, source_in = float(clip.get("source_out", 0)), float(clip.get("source_in", 0))
                if source_out <= source_in:
                    raise RenderWorkerError(f"Clip {index} source_out must be greater than source_in")
                if source_out > media_duration[asset_id] + 0.05:
                    raise RenderWorkerError(f"Clip {index} source_out exceeds media duration")

            await _report_progress(session_factory, job_id, lease_token, 60)
            output_path = temp / "render.mp4"
            plan = build_ffmpeg_plan(snapshot, asset_paths, str(output_path),
                                     render_profile=job.render_profile, asset_has_audio=media_audio)
            await execute_ffmpeg_plan(plan, timeout_seconds=timeout_seconds)
            output_info = await probe_media(str(output_path))
            validate_render_output(output_path, plan, output_info)
            await verify_output_decode(str(output_path), timeout_seconds=timeout_seconds)
            quality_report = await analyze_render_quality(
                str(output_path), includes_audio=plan.includes_audio,
                timeout_seconds=min(timeout_seconds, 900),
                intent_annotations=[item for item in snapshot.get("qc_intent", [])],
            )

            # Evidence extraction is advisory: a valid render remains publishable if
            # optional ASR or representative-frame extraction is unavailable.
            evidence_root = temp / "evidence"
            try:
                evidence = await extract_render_evidence(
                    str(output_path), evidence_root,
                    duration_seconds=output_info.duration_seconds,
                    includes_audio=plan.includes_audio,
                    asr_api_key=settings.evidence_asr_api_key,
                    asr_endpoint=settings.evidence_asr_endpoint,
                    asr_model=settings.evidence_asr_model,
                    vision_api_key=settings.evidence_vision_api_key,
                    vision_endpoint=settings.evidence_vision_endpoint,
                    vision_model=settings.evidence_vision_model,
                    timeout_seconds=min(timeout_seconds, settings.evidence_extraction_timeout_seconds),
                )
                _attach_signal_observations(evidence, quality_report.get("findings", []))
                evidence_prefix = f"evidence/{job.project_id}/{job.id}/attempt-{job.attempts}"
                for frame in evidence.get("keyframes", []):
                    frame_path = evidence_root / "frames" / frame["filename"]
                    frame_key = f"{evidence_prefix}/frames/{frame['filename']}"
                    await asyncio.to_thread(storage.put_file, frame_path, frame_key)
                    frame["object_key"] = frame_key
                    frame.pop("filename", None)
                audio_artifact = evidence.get("audio_artifact")
                if audio_artifact:
                    audio_path = evidence_root / audio_artifact["filename"]
                    audio_key = f"{evidence_prefix}/audio.mp3"
                    await asyncio.to_thread(storage.put_file, audio_path, audio_key)
                    audio_artifact["object_key"] = audio_key
                    audio_artifact.pop("filename", None)
                quality_report["evidence"] = evidence
                try:
                    story_analysis = await analyze_story_sequence(
                        snapshot, evidence,
                        api_key=settings.evidence_vision_api_key,
                        endpoint=settings.evidence_vision_endpoint,
                        model=settings.evidence_vision_model,
                        timeout_seconds=min(timeout_seconds, settings.evidence_extraction_timeout_seconds),
                    )
                    quality_report["story_analysis"] = story_analysis
                except Exception as exc:
                    story_analysis = {"status": "failed", "analysis_status": "failed",
                                      "segments": [], "findings": [], "semantic_findings": [],
                                      "limitations": [f"Story analysis unavailable: {str(exc)[:250]}"]}
                    quality_report["story_analysis"] = story_analysis
                try:
                    quality_report["story_continuity_graph"] = await build_story_continuity_graph(
                        snapshot, evidence, story_analysis,
                        api_key=settings.evidence_vision_api_key,
                        endpoint=settings.evidence_vision_endpoint,
                        model=settings.evidence_vision_model,
                        timeout_seconds=min(timeout_seconds, settings.evidence_extraction_timeout_seconds, 300),
                    )
                except Exception as exc:
                    quality_report["story_continuity_graph"] = {
                        "schema_version": "1.0", "status": "failed",
                        "engine": "story_continuity_graph_v1", "nodes": [], "edges": [],
                        "entity_extraction_status": "failed",
                        "limitations": [f"Continuity graph unavailable: {str(exc)[:250]}"],
                        "integrity": {"all_edges_have_evidence": True, "automatic_timeline_changes": 0},
                    }
            except EvidenceExtractionError as exc:
                quality_report["evidence"] = {
                    "schema_version": "1.0", "extraction_status": "failed",
                    "error": str(exc)[:1000], "keyframes": [],
                    "transcript_segments": [], "visual_observations": [],
                    "audio_observations": [], "visual_semantics_status": "not_configured",
                }

            job.quality_report = quality_report
            await session.flush()
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
