"""Strict allowlists for untrusted media parsed by FFmpeg/FFprobe.

The product temporarily accepts MP4/MOV only. WebM/Matroska, HEVC, and AV1 are disabled while the HDR+ metadata CVE remains unpatched. These controls deliberately
limit demuxers, protocols, and codecs before any media parser is invoked.
"""
from __future__ import annotations

import struct
from pathlib import Path

MEDIA_DEMUXER_WHITELIST = "mov"
MEDIA_PROTOCOL_WHITELIST = "file,pipe"
MEDIA_CODEC_WHITELIST = (
    "h264,prores,mpeg4,mjpeg,"
    "aac,mp3,pcm_s16le,pcm_s24le,alac,ac3,eac3,flac"
)
SUPPORTED_VIDEO_CODECS = frozenset({
    "h264", "prores", "mpeg4", "mjpeg",
})
SUPPORTED_AUDIO_CODECS = frozenset({
    "aac", "mp3", "pcm_s16le", "pcm_s24le",
    "alac", "ac3", "eac3", "flac",
})


def media_input_options() -> list[str]:
    """FFmpeg input options for uploaded MP4/MOV assets."""
    return [
        "-protocol_whitelist", MEDIA_PROTOCOL_WHITELIST,
        "-format_whitelist", MEDIA_DEMUXER_WHITELIST,
        "-codec_whitelist", MEDIA_CODEC_WHITELIST,
        "-max_alloc", "268435456",
        "-probesize", "10000000",
        "-analyzeduration", "10000000",
    ]


def media_input_args(path: str) -> list[str]:
    """Validate the container and return options plus its input path."""
    reject_pssh_atoms(str(path))
    return [*media_input_options(), "-i", str(path)]


class MediaInputPolicyError(ValueError):
    """Raised when an uploaded container violates the media input policy."""


_PSSH_BOX = b"pssh"
_CONTAINER_BOXES = {b"moov", b"moof"}
_MAX_BOXES_SCANNED = 100_000

def _box_header(handle, offset: int, parent_end: int) -> tuple[bytes, int, int]:
    if parent_end - offset < 8:
        raise MediaInputPolicyError("Malformed MP4 atom table")
    handle.seek(offset)
    header = handle.read(8)
    if len(header) != 8:
        raise MediaInputPolicyError("Truncated MP4 atom header")
    size32, box_type = struct.unpack(">I4s", header)
    header_size = 8
    if size32 == 1:
        extended = handle.read(8)
        if len(extended) != 8:
            raise MediaInputPolicyError("Truncated extended MP4 atom header")
        size = struct.unpack(">Q", extended)[0]
        header_size = 16
    elif size32 == 0:
        size = parent_end - offset
    else:
        size = size32
    if size < header_size or offset + size > parent_end:
        raise MediaInputPolicyError("Invalid MP4 atom size")
    return box_type, size, header_size

def reject_pssh_atoms(path: str) -> None:
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
                    raise MediaInputPolicyError("MP4 contains too many atoms")
                if box_type == _PSSH_BOX:
                    raise MediaInputPolicyError("DRM PSSH atoms are not supported")
                if box_type in _CONTAINER_BOXES:
                    child_offset = offset + header_size
                    child_end = offset + box_size
                    while child_offset < child_end:
                        child_type, child_size, _ = _box_header(handle, child_offset, child_end)
                        scanned += 1
                        if scanned > _MAX_BOXES_SCANNED:
                            raise MediaInputPolicyError("MP4 contains too many atoms")
                        if child_type == _PSSH_BOX:
                            raise MediaInputPolicyError("DRM PSSH atoms are not supported")
                        child_offset += child_size
                offset += box_size
    except OSError as exc:
        raise MediaInputPolicyError(f"Unable to inspect MP4 atom table: {exc}") from exc

