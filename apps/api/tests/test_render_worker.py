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
        clips=[{
            "id": uuid.uuid4(),
            "asset_id": asset.id,
            "track_id": "V1",
            "timeline_start": 0,
            "source_in": 0,
            "source_out": 2,
        }],
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
        return SimpleNamespace(duration_seconds=5.0, has_audio=False)

    async def fake_execute(plan, timeout_seconds=3600):
        from pathlib import Path
        Path(plan.output_path).write_bytes(b"rendered-video")
        return SimpleNamespace(output_path=plan.output_path, stderr_tail="")

    monkeypatch.setattr(worker_module, "probe_media", fake_probe)
    monkeypatch.setattr(worker_module, "execute_ffmpeg_plan", fake_execute)

    finished = await render_claimed_job(
        db_session, job.id, storage, tmp_path / "work", timeout_seconds=10
    )

    assert finished.status == "succeeded"
    assert finished.output_object_key == f"renders/{project.id}/{job.id}/attempt-1.mp4"
    assert storage._resolve(finished.output_object_key).read_bytes() == b"rendered-video"
