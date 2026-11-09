"""Fail-closed validation for encoded render outputs."""
from __future__ import annotations

from pathlib import Path

from app.media_probe import MediaInfo


class OutputIntegrityError(RuntimeError):
    pass


def validate_render_output(path: str | Path, plan, info: MediaInfo) -> None:
    output = Path(path)
    try:
        size = output.stat().st_size
    except OSError as exc:
        raise OutputIntegrityError("Rendered output file is missing or unreadable") from exc
    if size <= 0:
        raise OutputIntegrityError("Rendered output file is empty")
    if not info.format_name or "mp4" not in info.format_name.split(","):
        raise OutputIntegrityError("Rendered output is not a valid MP4 container")
    if not info.has_video or not info.video_codec:
        raise OutputIntegrityError("Rendered output has no decodable video stream")
    if info.video_codec != "h264":
        raise OutputIntegrityError(f"Unexpected video codec: {info.video_codec}")
    if plan.width is not None and info.width != plan.width:
        raise OutputIntegrityError(f"Output width mismatch: expected {plan.width}, got {info.width}")
    if plan.height is not None and info.height != plan.height:
        raise OutputIntegrityError(f"Output height mismatch: expected {plan.height}, got {info.height}")
    if info.has_audio != plan.includes_audio:
        raise OutputIntegrityError(
            f"Output audio presence mismatch: expected {plan.includes_audio}, got {info.has_audio}"
        )
    if plan.includes_audio and info.audio_codec != "aac":
        raise OutputIntegrityError(f"Unexpected audio codec: {info.audio_codec}")
    tolerance = max(0.35, 2.0 / plan.fps) if plan.fps else 0.5
    if abs(info.duration_seconds - plan.duration_seconds) > tolerance:
        raise OutputIntegrityError(
            f"Output duration mismatch: expected {plan.duration_seconds:.3f}s, "
            f"got {info.duration_seconds:.3f}s (tolerance {tolerance:.3f}s)"
        )
