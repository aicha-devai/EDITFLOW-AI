"""Context-aware, proposal-only QC critic.

This deterministic baseline uses timeline editorial metadata. It is deliberately
not presented as an LLM inference engine; every suggested annotation requires
explicit user approval before it can enter an immutable timeline revision.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RenderJob, TimelineVersion
from app.schemas import QCIntentRange, TimelineDocument
from app.versioning import VersionConflict, save_timeline


_INTENT_CUES = {
    "black_segment": (
        "blackout", "fade to black", "cut to black", "black screen",
        "intentional darkness", "before the reveal",
    ),
    "frozen_scene": (
        "freeze frame", "freeze-frame", "hold frame", "still frame",
        "evidence board", "pause on", "hold on this frame",
    ),
    "audio_silence": (
        "intentional silence", "silent pause", "dramatic pause",
        "pause before", "no dialogue", "let the silence",
    ),
}
_KIND_BY_FINDING = {
    "black_segment": "black_segment",
    "frozen_scene": "frozen_scene",
    "audio_silence": "audio_silence",
}


class QCCriticNotFound(Exception):
    pass


class QCCriticNotReady(Exception):
    pass


class StaleQCCriticBase(Exception):
    pass


def _clip_context(snapshot: dict[str, Any], start: float, end: float) -> list[str]:
    context: list[str] = []
    for clip in snapshot.get("clips", []):
        clip_start = float(clip.get("timeline_start", 0))
        clip_end = clip_start + max(
            0.0, float(clip.get("source_out", 0)) - float(clip.get("source_in", 0))
        )
        if clip_start <= end and clip_end >= start:
            value = clip.get("rationale")
            if isinstance(value, str) and value.strip():
                context.append(value.strip())
    return context


def _overlaps(start: float, end: float, other_start: Any, other_end: Any) -> bool:
    try:
        left, right = float(other_start), float(other_end)
    except (TypeError, ValueError):
        return False
    return right > left and left < end and right > start


def _temporal_evidence(
    quality_report: dict[str, Any],
    timeline_snapshot: dict[str, Any],
    start: float,
    end: float,
) -> dict[str, Any]:
    """Collect only timestamped evidence already attached to the render report."""
    bundle = quality_report.get("evidence")
    if not isinstance(bundle, dict):
        bundle = {}

    transcript = []
    for item in bundle.get("transcript_segments", []):
        if not isinstance(item, dict) or not _overlaps(
            start, end, item.get("start_seconds"), item.get("end_seconds")
        ):
            continue
        text = item.get("text")
        if isinstance(text, str) and text.strip():
            transcript.append({
                "start_seconds": float(item["start_seconds"]),
                "end_seconds": float(item["end_seconds"]),
                "text": text.strip()[:500],
                "source": "render_evidence.transcript_segments",
            })

    keyframes = []
    for item in bundle.get("keyframes", []):
        if not isinstance(item, dict):
            continue
        timestamp = item.get("timestamp_seconds")
        end_seconds = item.get("end_seconds", timestamp)
        if timestamp is None or not _overlaps(start, end, timestamp, end_seconds):
            continue
        keyframes.append({
            "timestamp_seconds": float(timestamp),
            "end_seconds": float(end_seconds),
            "object_key": item.get("object_key"),
            "sample_type": item.get("sample_type", "unknown"),
            "source": "render_evidence.keyframes",
        })

    observations = []
    for modality, key in (
        ("visual", "visual_observations"),
        ("audio", "audio_observations"),
    ):
        for item in bundle.get(key, []):
            if not isinstance(item, dict) or not _overlaps(
                start, end, item.get("start_seconds"), item.get("end_seconds")
            ):
                continue
            description = item.get("description")
            if isinstance(description, str) and description.strip():
                observations.append({
                    "modality": modality,
                    "start_seconds": float(item["start_seconds"]),
                    "end_seconds": float(item["end_seconds"]),
                    "description": description.strip()[:500],
                    "source": f"render_evidence.{key}",
                })

    beat_ids = {
        str(clip.get("story_beat_id"))
        for clip in timeline_snapshot.get("clips", [])
        if clip.get("story_beat_id")
        and _overlaps(
            start, end,
            clip.get("timeline_start", 0),
            float(clip.get("timeline_start", 0))
            + max(0.0, float(clip.get("source_out", 0)) - float(clip.get("source_in", 0))),
        )
    }
    beats = []
    sequence = timeline_snapshot.get("sequence", {})
    beat_items = sequence.get("story_beats", []) if isinstance(sequence, dict) else []
    for beat in beat_items:
        if not isinstance(beat, dict) or str(beat.get("id")) not in beat_ids:
            continue
        beats.append({
            "id": str(beat.get("id")),
            "title": str(beat.get("title") or "Untitled story beat")[:160],
        })

    return {
        "transcript_segments": transcript,
        "keyframes": keyframes,
        "observations": observations,
        "story_beats": beats,
        "available_modalities": sorted(
            (["transcript"] if transcript else [])
            + (["visual"] if any(x["modality"] == "visual" for x in observations) else [])
            + (["audio"] if any(x["modality"] == "audio" for x in observations) else [])
        ),
    }


def generate_qc_critic_proposals(
    quality_report: dict[str, Any] | None,
    timeline_snapshot: dict[str, Any],
) -> dict[str, Any]:
    """Return stable, explainable suggestions; never mutate the timeline/report."""
    if not quality_report:
        return {"status": "unavailable", "proposals": [], "message": "No QC report is available."}

    global_context = [
        value for value in timeline_snapshot.get("editorial_notes", [])
        if isinstance(value, str) and value.strip()
    ]
    sequence = timeline_snapshot.get("sequence", {})
    for key in ("story_summary", "narration", "creative_direction", "tone"):
        value = sequence.get(key) if isinstance(sequence, dict) else None
        if isinstance(value, str) and value.strip():
            global_context.append(value.strip())

    proposals = []
    for finding in quality_report.get("findings", []):
        if finding.get("severity", "warning") != "warning" or finding.get("intentional"):
            continue
        code = finding.get("code")
        kind = _KIND_BY_FINDING.get(code)
        start, end = finding.get("start_seconds"), finding.get("end_seconds")
        if not kind or start is None or end is None or float(end) <= float(start):
            continue

        local_context = _clip_context(timeline_snapshot, float(start), float(end))
        temporal_evidence = _temporal_evidence(
            quality_report, timeline_snapshot, float(start), float(end)
        )
        matched_cues = []
        matched_sources = []
        for source_name, values in (
            ("overlapping_clip_rationale", local_context),
            ("editorial_or_story_notes", global_context),
        ):
            joined = " ".join(values).casefold()
            cues = [cue for cue in _INTENT_CUES[kind] if re.search(r"(?<!\w)" + re.escape(cue) + r"(?!\w)", joined)]
            if cues:
                matched_cues.extend(cues)
                matched_sources.append(source_name)

        if "overlapping_clip_rationale" in matched_sources:
            confidence = 0.86
            recommendation = "mark_intentional"
            explanation = "An overlapping clip rationale explicitly describes a matching storytelling device."
        elif matched_cues:
            confidence = 0.72
            recommendation = "mark_intentional"
            explanation = "Editorial or story notes contain language consistent with an intentional storytelling device; verify the exact timing."
        else:
            confidence = 0.48
            recommendation = "inspect_as_potential_issue"
            explanation = "No matching intent is documented in the timeline. Treat this as a possible production issue until reviewed."

        reason = (
            f"Suggested intentional {kind.replace('_', ' ')}: "
            + (", ".join(sorted(set(matched_cues))) if matched_cues else "editor review required")
        )
        identity = {
            "kind": kind,
            "start_seconds": round(float(start), 3),
            "end_seconds": round(float(end), 3),
            "finding_code": code,
        }
        proposal_id = hashlib.sha256(
            json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()[:20]
        proposals.append({
            "proposal_id": proposal_id,
            "finding_code": code,
            "kind": kind,
            "start_seconds": identity["start_seconds"],
            "end_seconds": identity["end_seconds"],
            "recommendation": recommendation,
            "confidence": confidence,
            "confidence_type": "heuristic_score_not_probability",
            "matched_cues": sorted(set(matched_cues)),
            "evidence_sources": matched_sources,
            "temporal_evidence": temporal_evidence,
            "explanation": explanation,
            "suggested_reason": reason[:300],
            "requires_user_approval": True,
        })

    return {
        "status": "proposals" if proposals else "no_actionable_findings",
        "engine": "deterministic_context_critic_v1",
        "proposals": proposals,
        "automatic_changes": 0,
    }


async def approve_qc_intent_proposals(
    session: AsyncSession,
    project_id: UUID,
    job_id: UUID,
    proposal_ids: list[str],
    expected_version: int,
):
    if not proposal_ids:
        raise ValueError("At least one proposal_id must be approved")

    job = await session.scalar(select(RenderJob).where(
        RenderJob.id == job_id, RenderJob.project_id == project_id
    ))
    if job is None:
        raise QCCriticNotFound()
    if job.status != "succeeded" or not job.quality_report:
        raise QCCriticNotReady()

    latest = await session.scalar(
        select(TimelineVersion).where(TimelineVersion.project_id == project_id)
        .order_by(TimelineVersion.version.desc()).limit(1)
    )
    if latest is None or latest.id != job.timeline_version_id:
        raise StaleQCCriticBase(
            "The project timeline has changed since this render. Render the current version before approving QC suggestions."
        )
    if latest.version != expected_version:
        raise VersionConflict(
            f"Expected version {expected_version}, current version is {latest.version}"
        )

    critic = generate_qc_critic_proposals(job.quality_report, job.timeline_snapshot)
    by_id = {item["proposal_id"]: item for item in critic["proposals"]}
    if len(set(proposal_ids)) != len(proposal_ids):
        raise ValueError("Duplicate proposal_id values are not allowed")
    unknown = set(proposal_ids) - set(by_id)
    if unknown:
        raise ValueError("One or more proposal IDs are invalid for this render")
    selected = [by_id[item] for item in proposal_ids]
    if any(item["recommendation"] != "mark_intentional" for item in selected):
        raise ValueError("Only proposals recommending mark_intentional can be approved as intent annotations")

    timeline = TimelineDocument.model_validate(job.timeline_snapshot)
    existing = [item.model_dump(mode="json") for item in timeline.qc_intent]
    additions = [{
        "kind": item["kind"],
        "start_seconds": item["start_seconds"],
        "end_seconds": item["end_seconds"],
        "reason": item["suggested_reason"],
    } for item in selected]
    merged = existing + [item for item in additions if item not in existing]
    if len(merged) > 100:
        raise ValueError("Approving these proposals would exceed the 100 QC annotation limit")
    timeline.qc_intent = [QCIntentRange.model_validate(item) for item in merged]

    row, created = await save_timeline(
        session, project_id, timeline, expected_version,
        message=f"Approved {len(additions)} AI QC Critic intent suggestion(s) from render {job_id}",
    )
    return row, created, len(additions)
