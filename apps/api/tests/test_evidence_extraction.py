import asyncio
from pathlib import Path

import pytest

from app.evidence_extraction import extract_render_evidence
from app.qc_critic import generate_qc_critic_proposals


@pytest.mark.asyncio
async def test_extracts_timestamped_keyframes_and_audio_artifact(tmp_path):
    source = tmp_path / "source.mp4"
    process = await asyncio.create_subprocess_exec(
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
        "-f", "lavfi", "-i", "testsrc=size=320x240:rate=10:duration=3",
        "-f", "lavfi", "-i", "sine=frequency=1000:duration=3",
        "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-y", str(source),
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    assert process.returncode == 0, stderr.decode("utf-8", errors="replace")

    evidence = await extract_render_evidence(
        str(source), tmp_path / "evidence",
        duration_seconds=3.0, includes_audio=True, asr_api_key=None,
    )
    assert evidence["extraction_status"] == "completed"
    assert evidence["keyframes"]
    assert all((tmp_path / "evidence" / "frames" / item["filename"]).is_file()
               for item in evidence["keyframes"])
    assert evidence["transcription"]["status"] == "not_configured"
    assert evidence["transcript_segments"] == []
    assert (tmp_path / "evidence" / "audio.mp3").is_file()
    assert evidence["audio_artifact"]["sample_rate_hz"] == 16000


def test_critic_receives_timestamped_extracted_keyframes_and_transcript():
    report = {
        "findings": [{"code": "frozen_scene", "start_seconds": 2, "end_seconds": 4}],
        "evidence": {
            "keyframes": [
                {"timestamp_seconds": 1, "end_seconds": 2, "object_key": "frames/a.jpg"},
                {"timestamp_seconds": 2.5, "end_seconds": 3, "object_key": "frames/b.jpg",
                 "sample_type": "scene_change"},
            ],
            "transcript_segments": [
                {"start_seconds": 2.2, "end_seconds": 2.8, "text": "Look at this."},
            ],
        },
    }
    proposal = generate_qc_critic_proposals(report, {})["proposals"][0]
    evidence = proposal["temporal_evidence"]
    assert len(evidence["keyframes"]) == 1
    assert evidence["keyframes"][0]["object_key"] == "frames/b.jpg"
    assert evidence["transcript_segments"][0]["text"] == "Look at this."
