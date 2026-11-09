"""Real FFmpeg integration test (requires ffmpeg + ffprobe binaries)."""
import asyncio
import shutil
import subprocess

import pytest

from app.media_probe import probe_media
from app.render_engine import build_ffmpeg_plan
from app.render_executor import execute_ffmpeg_plan


@pytest.mark.asyncio
async def test_real_ffmpeg_render_produces_valid_mp4(tmp_path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg integration test requires ffmpeg and ffprobe")

    source = tmp_path / "source.mp4"
    output = tmp_path / "rendered.mp4"

    # A deterministic synthetic clip avoids downloading copyrighted or external media.
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-f", "lavfi", "-i", "testsrc=size=320x240:rate=24:duration=2",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100:duration=2",
            "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", str(source),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )

    asset_id = "synthetic-asset"
    snapshot = {
        "sequence": {"width": 360, "height": 640, "fps": 24},
        "clips": [
            {
                "id": "clip-1",
                "asset_id": asset_id,
                "timeline_start": 0,
                "source_in": 0.25,
                "source_out": 1.75,
            }
        ],
    }
    plan = build_ffmpeg_plan(
        snapshot,
        {asset_id: str(source)},
        str(output),
        asset_has_audio={asset_id: True},
    )

    result = await execute_ffmpeg_plan(plan, timeout_seconds=60)
    assert result.output_path == str(output)
    assert output.is_file() and output.stat().st_size > 1000

    info = await probe_media(str(output))
    assert info.has_video is True
    assert info.has_audio is True
    assert (info.width, info.height) == (360, 640)
    assert 1.35 <= info.duration_seconds <= 1.7
    assert info.video_codec == "h264"
