"""Bounded ffprobe metadata inspection for local media assets."""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass


class MediaProbeError(RuntimeError):
    pass


@dataclass(frozen=True)
class MediaInfo:
    duration_seconds: float
    has_video: bool
    has_audio: bool
    width: int | None
    height: int | None
    video_codec: str | None
    audio_codec: str | None


async def probe_media(path: str, timeout_seconds: int = 30) -> MediaInfo:
    if timeout_seconds < 1 or timeout_seconds > 300:
        raise ValueError("timeout_seconds must be between 1 and 300")
    try:
        process = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error", "-show_entries",
            "format=duration:stream=codec_type,codec_name,width,height",
            "-of", "json", path,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise MediaProbeError("ffprobe executable was not found on the worker") from exc
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        process.kill()
        await process.communicate()
        raise MediaProbeError("ffprobe timed out") from None
    if process.returncode != 0:
        detail = (stderr or b"").decode("utf-8", errors="replace")[-2000:]
        raise MediaProbeError(f"ffprobe failed: {detail}")
    try:
        payload = json.loads(stdout.decode("utf-8"))
        streams = payload.get("streams", [])
        video = next((s for s in streams if s.get("codec_type") == "video"), None)
        audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
        duration = float(payload.get("format", {}).get("duration", 0))
        if duration <= 0:
            raise ValueError("missing positive duration")
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise MediaProbeError(f"ffprobe returned invalid media metadata: {exc}") from exc
    if video is None:
        raise MediaProbeError("Input asset has no video stream")
    return MediaInfo(
        duration_seconds=duration,
        has_video=True,
        has_audio=audio is not None,
        width=int(video["width"]) if video.get("width") else None,
        height=int(video["height"]) if video.get("height") else None,
        video_codec=video.get("codec_name"),
        audio_codec=audio.get("codec_name") if audio else None,
    )
