"""Scene-boundary detection using the worker restricted system FFmpeg binary."""
from __future__ import annotations

import math
import re
import subprocess
from pathlib import Path

from app.media_policy import media_input_args


class SceneDetectionError(RuntimeError):
    """Raised when restricted FFmpeg cannot inspect the supplied media."""


def detect_scene_changes(video_path: str, threshold: float = 0.30) -> list[float]:
    """Return scene-boundary timestamps using the allowlisted FFmpeg input path."""
    if not 0.05 <= threshold <= 0.95:
        raise ValueError("threshold must be between 0.05 and 0.95")
    if not Path(video_path).is_file():
        raise SceneDetectionError("Video file does not exist")
    argv = [
        "ffmpeg", "-hide_banner", "-nostdin", "-v", "info",
        *media_input_args(video_path),
        "-vf", f"select='gt(scene,{threshold})',showinfo",
        "-an", "-f", "null", "-",
    ]
    try:
        result = subprocess.run(
            argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE, timeout=300, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SceneDetectionError(f"Restricted FFmpeg scene detection failed: {exc}") from exc
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace")[-1200:]
        raise SceneDetectionError(f"Restricted FFmpeg scene detection failed: {detail}")
    values = [float(value) for value in re.findall(
        rb"pts_time:([0-9]+(?:\.[0-9]+)?)", result.stderr,
    )]
    return sorted(value for value in values if math.isfinite(value) and value >= 0)
