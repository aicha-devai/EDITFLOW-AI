import uuid
from types import SimpleNamespace

import pytest

from app.models import Asset, Project
from app.rendering import claim_next_render_job, create_render_job
from app.schemas import TimelineDocument
from app.storage import LocalObjectStorage
from app.versioning import save_timeline
from app.render_worker import render_claimed_job


@pytest.mark.asyncio
async def test_worker_renders_pinned_snapshot_and_stores_output(db_session, tmp_path, monkeypatch):
    import app.render_worker as worker_module

    project = Project(title="End-to-end local worker")
    db_session.add(project)
    await db_session.flush()
    asset = Asset(project_id=project.id, object_key="uploads/source.mp4")
    db_session.add(asset)
    await db_session.flush()
    timeline = TimelineDocument(
        project_id=project.id,
        sequence={"width": 1080, "height": 1920, "fps": 30},
        clips=[{"id": uuid.uuid4(), "asset_id": asset.id, "track_id": "V1",
                "timeline_start": 0, "source_in": 0, "source_out": 2}],
    )
    await save_timeline(db_session, project.id, timeline, expected_version=0)
    job, _ = await create_render_job(db_session, project.id)
    claimed = await claim_next_render_job(db_session)
    assert claimed.id == job.id

    storage = LocalObjectStorage(tmp_path / "objects")
    source = storage.root / "uploads" / "source.mp4"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"fake-media")

    async def fake_probe(path):
        if str(path).endswith("render.mp4"):
            return SimpleNamespace(
                duration_seconds=2.0, has_video=True, has_audio=False,
                width=1080, height=1920, video_codec="h264",
                audio_codec=None, format_name="mov,mp4,m4a,3gp,3g2,mj2",
            )
        return SimpleNamespace(duration_seconds=5.0, has_audio=False)

    async def fake_execute(plan, timeout_seconds=3600):
        from pathlib import Path
        Path(plan.output_path).write_bytes(b"rendered-video")
        return SimpleNamespace(output_path=plan.output_path, stderr_tail="")

    monkeypatch.setattr(worker_module, "probe_media", fake_probe)
    monkeypatch.setattr(worker_module, "execute_ffmpeg_plan", fake_execute)
    async def fake_decode(_path, timeout_seconds=3600):
        return ""
    monkeypatch.setattr(worker_module, "verify_output_decode", fake_decode)
    async def fake_qc(_path, *, includes_audio, timeout_seconds=900, intent_annotations=None):
        return {"schema_version": "1.0", "status": "warnings", "summary": {"warning_count": 1},
                "findings": [{"code": "frozen_scene", "severity": "warning"}]}
    monkeypatch.setattr(worker_module, "analyze_render_quality", fake_qc)
    finished = await render_claimed_job(
        db_session, job.id, storage, tmp_path / "work", timeout_seconds=10
    )

    assert finished.status == "succeeded"
    assert finished.quality_report["status"] == "warnings"
    assert finished.quality_report["findings"][0]["code"] == "frozen_scene"
    assert finished.output_object_key == f"renders/{project.id}/{job.id}/attempt-1.mp4"
    assert storage._resolve(finished.output_object_key).read_bytes() == b"rendered-video"


@pytest.mark.asyncio
async def test_worker_fails_job_and_does_not_publish_invalid_output(db_session, tmp_path, monkeypatch):
    import app.render_worker as worker_module

    project = Project(title="Invalid output must not publish")
    db_session.add(project)
    await db_session.flush()
    asset = Asset(project_id=project.id, object_key="uploads/source.mp4")
    db_session.add(asset)
    await db_session.flush()
    timeline = TimelineDocument(
        project_id=project.id,
        sequence={"width": 1080, "height": 1920, "fps": 30},
        clips=[{"id": uuid.uuid4(), "asset_id": asset.id, "track_id": "V1",
                "timeline_start": 0, "source_in": 0, "source_out": 2}],
    )
    await save_timeline(db_session, project.id, timeline, expected_version=0)
    job, _ = await create_render_job(db_session, project.id)
    await claim_next_render_job(db_session)

    storage = LocalObjectStorage(tmp_path / "invalid-objects")
    source = storage.root / "uploads" / "source.mp4"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"fake-media")

    async def fake_probe(path):
        if str(path).endswith("render.mp4"):
            return SimpleNamespace(
                duration_seconds=2.0, has_video=True, has_audio=False,
                width=1080, height=1920, video_codec="h264",
                audio_codec=None, format_name="mov,mp4,m4a,3gp,3g2,mj2",
            )
        return SimpleNamespace(duration_seconds=5.0, has_audio=False)

    async def fake_execute(plan, timeout_seconds=3600):
        from pathlib import Path
        Path(plan.output_path).write_bytes(b"encoded-but-wrong-size")
        return SimpleNamespace(output_path=plan.output_path, stderr_tail="")

    async def reject_decode(_path, timeout_seconds=3600):
        raise worker_module.RenderWorkerError("FFmpeg output decode verification failed: corrupt frame")

    monkeypatch.setattr(worker_module, "probe_media", fake_probe)
    monkeypatch.setattr(worker_module, "execute_ffmpeg_plan", fake_execute)
    monkeypatch.setattr(worker_module, "verify_output_decode", reject_decode)
    finished = await render_claimed_job(
        db_session, job.id, storage, tmp_path / "invalid-work", timeout_seconds=10
    )

    assert finished.status == "queued"  # retry policy requeues a failed attempt
    assert "decode verification failed" in finished.error_message
    assert finished.output_object_key is None
