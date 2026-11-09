"""Perceptual video/audio QC using FFmpeg filters; diagnostics never fail a render."""
from __future__ import annotations

import asyncio
import re
from typing import Any


class PerceptualQCError(RuntimeError):
    pass


def _events(stderr: str, start_pattern: str, end_pattern: str, code: str, message: str) -> list[dict[str, Any]]:
    starts = [float(value) for value in re.findall(start_pattern, stderr)]
    ends = [float(value) for value in re.findall(end_pattern, stderr)]
    items = []
    for index, start in enumerate(starts):
        end = ends[index] if index < len(ends) else None
        items.append({
            "code": code, "severity": "warning", "message": message,
            "start_seconds": round(start, 3),
            "end_seconds": round(end, 3) if end is not None else None,
            "duration_seconds": round(max(0.0, end - start), 3) if end is not None else None,
        })
    return items


async def analyze_render_quality(
    output_path: str,
    *,
    includes_audio: bool,
    timeout_seconds: int = 900,
    black_min_duration: float = 0.5,
    freeze_min_duration: float = 2.0,
    silence_min_duration: float = 1.0,
    silence_noise_db: float = -50.0,
    intent_annotations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run black/freeze/silence/peak/clipping diagnostics. Findings are warnings only."""
    if not 1 <= timeout_seconds <= 21600:
        raise ValueError("timeout_seconds must be between 1 and 21600")
    if min(black_min_duration, freeze_min_duration, silence_min_duration) <= 0:
        raise ValueError("QC duration thresholds must be positive")

    video_filter = (
        f"blackdetect=d={black_min_duration}:pix_th=0.10,"
        f"freezedetect=n=-50dB:d={freeze_min_duration}"
    )
    argv = ["ffmpeg", "-hide_banner", "-nostdin", "-v", "info", "-i", output_path,
            "-vf", video_filter]
    if includes_audio:
        audio_filter = (
            f"silencedetect=noise={silence_noise_db}dB:d={silence_min_duration},"
            "astats=metadata=1:reset=0"
        )
        argv.extend(["-af", audio_filter])
    argv.extend(["-map", "0:v:0", "-map", "0:a?" if includes_audio else "-an",
                 "-f", "null", "-"])

    try:
        process = await asyncio.create_subprocess_exec(
            *argv, stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise PerceptualQCError("FFmpeg executable was not found for perceptual QC") from exc
    try:
        _, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        process.kill()
        await process.communicate()
        raise PerceptualQCError(f"Perceptual QC exceeded its {timeout_seconds}s timeout") from None
    except asyncio.CancelledError:
        process.kill()
        await process.communicate()
        raise

    output = (stderr or b"").decode("utf-8", errors="replace")
    if process.returncode != 0:
        raise PerceptualQCError(
            f"Perceptual QC analysis failed (exit {process.returncode}): {output[-2000:]}"
        )

    findings: list[dict[str, Any]] = []
    findings += _events(
        output, r"black_start:([0-9.]+)", r"black_end:([0-9.]+)",
        "black_segment", "Sustained near-black segment detected; confirm it is intentional.",
    )
    findings += _events(
        output, r"freeze_start:([0-9.]+)", r"freeze_end:([0-9.]+)",
        "frozen_scene", "Potential frozen scene detected; confirm the still frame is intentional.",
    )
    if includes_audio:
        findings += _events(
            output, r"silence_start:([0-9.]+)", r"silence_end:([0-9.]+)",
            "audio_silence", "Sustained audio silence detected; confirm narration/music is not missing.",
        )
        clipped = re.findall(r"Number of clipped samples:\s*(\d+)", output, flags=re.IGNORECASE)
        clipped_count = max((int(value) for value in clipped), default=0)
        if clipped_count:
            findings.append({
                "code": "audio_clipping", "severity": "warning",
                "message": "Audio clipping samples detected; reduce gain or limiter threshold.",
                "sample_count": clipped_count,
            })
        peaks = re.findall(r"Peak level dB:\s*(-?inf|-?[0-9.]+)", output, flags=re.IGNORECASE)
        finite_peaks = [float(value) for value in peaks if value.lower() != "-inf"]
        if finite_peaks and max(finite_peaks) >= -0.1:
            findings.append({
                "code": "audio_peak_near_full_scale", "severity": "warning",
                "message": "Audio peak is at or near 0 dBFS; check headroom and possible distortion.",
                "peak_dbfs": round(max(finite_peaks), 2),
            })

    # Explicit timeline annotations suppress only matching event types fully covered by the declared range.
    # Keep the diagnostic visible in the report, but downgrade it to informational.
    annotations = intent_annotations or []
    for finding in findings:
        start = finding.get("start_seconds")
        end = finding.get("end_seconds")
        if start is None:
            continue
        event_end = end if end is not None else start
        for annotation in annotations:
            if annotation.get("kind") != finding["code"]:
                continue
            if float(annotation["start_seconds"]) <= float(start) and float(annotation["end_seconds"]) >= event_end:
                finding["intentional"] = True
                finding["severity"] = "info"
                finding["classification"] = "intentional"
                finding["intent_reason"] = annotation["reason"]
                break

    warning_count = sum(item["severity"] == "warning" for item in findings)
    intentional_count = sum(item.get("intentional", False) for item in findings)
    return {
        "schema_version": "1.1",
        "status": "warnings" if warning_count else ("intentional_only" if intentional_count else "passed"),
        "analysis": {
            "black_min_duration_seconds": black_min_duration,
            "freeze_min_duration_seconds": freeze_min_duration,
            "silence_min_duration_seconds": silence_min_duration if includes_audio else None,
            "silence_noise_db": silence_noise_db if includes_audio else None,
            "audio_analyzed": includes_audio,
        },
        "summary": {
            "warning_count": warning_count,\n            "intentional_findings": intentional_count,
            "black_segments": sum(item["code"] == "black_segment" for item in findings),
            "frozen_scenes": sum(item["code"] == "frozen_scene" for item in findings),
            "audio_silence_events": sum(item["code"] == "audio_silence" for item in findings),
            "audio_clipping": sum(item["code"] == "audio_clipping" for item in findings),
        },
        "findings": findings,\n        "intent_annotations_applied": intentional_count,
    }
