"""Bounded ffprobe metadata inspection for source and rendered media."""
from __future__ import annotations

import asyncio
import json
import struct
from dataclasses import dataclass
from pathlib import Path

from app.media_policy import (
    SUPPORTED_AUDIO_CODECS,
    SUPPORTED_VIDEO_CODECS,
    media_input_options,
)


class MediaProbeError(RuntimeError):
    pass


_PSSH_BOX = b"pssh"
_CONTAINER_BOXES = {b"moov", b"moof"}
_MAX_BOXES_SCANNED = 100_000

def _box_header(handle, offset: int, parent_end: int) -> tuple[bytes, int, int]:
    if parent_end - offset < 8:
        raise MediaProbeError("Malformed MP4 atom table")
    handle.seek(offset)
    header = handle.read(8)
    if len(header) != 8:
        raise MediaProbeError("Truncated MP4 atom header")
    size32, box_type = struct.unpack(">I4s", header)
    header_size = 8
    if size32 == 1:
        extended = handle.read(8)
        if len(extended) != 8:
            raise MediaProbeError("Truncated extended MP4 atom header")
        size = struct.unpack(">Q", extended)[0]
        header_size = 16
    elif size32 == 0:
        size = parent_end - offset
    else:
        size = size32
    if size < header_size or offset + size > parent_end:
        raise MediaProbeError("Invalid MP4 atom size")
    return box_type, size, header_size

def _reject_pssh_atoms(path: str) -> None:
    """Reject ISO-BMFF PSSH atoms before ffprobe parses an uploaded source.

    DRM-protected uploads are not supported. This preflight reads only atom
    headers and never loads media payloads.
    """
    source = Path(path)
    if not source.is_file():
        return  # ffprobe will report a missing or unreadable source.
    try:
        file_size = source.stat().st_size
        scanned = 0
        with source.open("rb") as handle:
            offset = 0
            while offset < file_size:
                box_type, box_size, header_size = _box_header(handle, offset, file_size)
                scanned += 1
                if scanned > _MAX_BOXES_SCANNED:
                    raise MediaProbeError("MP4 contains too many atoms")
                if box_type == _PSSH_BOX:
                    raise MediaProbeError("DRM PSSH atoms are not supported")
                if box_type in _CONTAINER_BOXES:
                    child_offset = offset + header_size
                    child_end = offset + box_size
                    while child_offset < child_end:
                        child_type, child_size, _ = _box_header(handle, child_offset, child_end)
                        scanned += 1
                        if scanned > _MAX_BOXES_SCANNED:
                            raise MediaProbeError("MP4 contains too many atoms")
                        if child_type == _PSSH_BOX:
                            raise MediaProbeError("DRM PSSH atoms are not supported")
                        child_offset += child_size
                offset += box_size
    except OSError as exc:
        raise MediaProbeError(f"Unable to inspect MP4 atom table: {exc}") from exc

@dataclass(frozen=True)
class MediaInfo:
    duration_seconds: float
    has_video: bool
    has_audio: bool
    width: int | None
    height: int | None
    video_codec: str | None
    audio_codec: str | None
    format_name: str | None = None


async def probe_media(path: str, timeout_seconds: int = 30) -> MediaInfo:
    if timeout_seconds < 1 or timeout_seconds > 300:
        raise ValueError("timeout_seconds must be between 1 and 300")
    _reject_pssh_atoms(path)
    try:
        process = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error", *media_input_options(),
            "-show_entries",
            "format=duration,format_name:stream=codec_type,codec_name,width,height",
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
    except asyncio.CancelledError:
        process.kill()
        await process.communicate()
        raise
    if process.returncode != 0:
        detail = (stderr or b"").decode("utf-8", errors="replace")[-2000:]
        raise MediaProbeError(f"ffprobe failed: {detail}")
    try:
        payload = json.loads(stdout.decode("utf-8"))
        streams = payload.get("streams", [])
        video = next((s for s in streams if s.get("codec_type") == "video"), None)
        audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
        fmt = payload.get("format", {})
        duration = float(fmt.get("duration", 0))
        if duration <= 0:
            raise ValueError("missing positive duration")
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise MediaProbeError(f"ffprobe returned invalid media metadata: {exc}") from exc
    if video is None:
        raise MediaProbeError("Input asset has no video stream")
    format_name = fmt.get("format_name")
    formats = set(str(format_name or "").split(","))
    if "mov" not in formats:
        raise MediaProbeError("Unsupported media container; only MP4 and MOV are accepted")
    video_codec = video.get("codec_name")
    if video_codec not in SUPPORTED_VIDEO_CODECS:
        raise MediaProbeError(f"Unsupported video codec: {video_codec or 'unknown'}")
    audio_codec = audio.get("codec_name") if audio else None
    if audio_codec is not None and audio_codec not in SUPPORTED_AUDIO_CODECS:
        raise MediaProbeError(f"Unsupported audio codec: {audio_codec}")
    return MediaInfo(
        duration_seconds=duration,
        has_video=True,
        has_audio=audio is not None,
        width=int(video["width"]) if video.get("width") else None,
        height=int(video["height"]) if video.get("height") else None,
        video_codec=video_codec,
        audio_codec=audio_codec,
        format_name=format_name,
    )
