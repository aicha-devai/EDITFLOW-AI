"""Async subprocess adapter for the FFmpeg planner.

The caller is responsible for committing the claimed job before invoking this
long-running operation and for recording success/failure in a later transaction.
"""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass

from app.render_engine import RenderPlan


class RenderExecutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class RenderExecutionResult:
    output_path: str
    stderr_tail: str


async def execute_ffmpeg_plan(
    plan: RenderPlan,
    timeout_seconds: int = 3600,
) -> RenderExecutionResult:
    if timeout_seconds < 1 or timeout_seconds > 21600:
        raise ValueError("timeout_seconds must be between 1 and 21600")
    if not plan.argv or plan.argv[0] != "ffmpeg":
        raise ValueError("RenderPlan must start with the ffmpeg executable")

    try:
        process = await asyncio.create_subprocess_exec(
            *plan.argv,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise RenderExecutionError("FFmpeg executable was not found on the worker") from exc

    try:
        _, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        process.kill()
        await process.communicate()
        raise RenderExecutionError(f"FFmpeg exceeded its {timeout_seconds}s execution timeout") from None
    except asyncio.CancelledError:
        # A cancellation or lost lease must not leave an orphaned encoder running.
        process.kill()
        await process.communicate()
        raise

    stderr_text = (stderr or b"").decode("utf-8", errors="replace")
    if process.returncode != 0:
        raise RenderExecutionError(
            f"FFmpeg exited with code {process.returncode}: {stderr_text[-4000:]}"
        )
    try:
        output_size = os.path.getsize(plan.output_path)
    except OSError as exc:
        raise RenderExecutionError("FFmpeg reported success but the output file is missing") from exc
    if output_size <= 0:
        raise RenderExecutionError("FFmpeg produced an empty output file")
    return RenderExecutionResult(plan.output_path, stderr_text[-4000:])


async def verify_output_decode(
    output_path: str,
    timeout_seconds: int = 3600,
) -> str:
    """Decode every video/audio stream without re-encoding; fail on any decoder error."""
    if timeout_seconds < 1 or timeout_seconds > 21600:
        raise ValueError("timeout_seconds must be between 1 and 21600")
    argv = (
        "ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-xerror",
        "-err_detect", "explode", "-i", output_path, "-map", "0:v?", "-map", "0:a?", "-f", "null", "-",
    )
    try:
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise RenderExecutionError("FFmpeg executable was not found for output decode verification") from exc

    try:
        _, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        process.kill()
        await process.communicate()
        raise RenderExecutionError(
            f"FFmpeg output decode verification exceeded its {timeout_seconds}s timeout"
        ) from None
    except asyncio.CancelledError:
        process.kill()
        await process.communicate()
        raise

    stderr_text = (stderr or b"").decode("utf-8", errors="replace")
    if process.returncode != 0:
        raise RenderExecutionError(
            f"FFmpeg output decode verification failed (exit {process.returncode}): "
            f"{stderr_text[-4000:]}"
        )
    return stderr_text[-4000:]
