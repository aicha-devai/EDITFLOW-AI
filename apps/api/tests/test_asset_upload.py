import hashlib
import subprocess
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import HTTPException
from starlette.datastructures import Headers, UploadFile

from app import main
from app.models import Asset, Project, TimelineAssetReference, TimelineVersion, User
from app.storage import LocalObjectStorage


@pytest.mark.asyncio
async def test_upload_validates_real_video_stores_sha_and_links_timeline(db_session, tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc2=size=160x284:rate=12:duration=2",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
        "-shortest", "-c:v", "libx264", "-preset", "ultrafast",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart", "-y", str(source),
    ], check=True)
    video_bytes = source.read_bytes()
    user = User(email="upload-owner@example.com", password_hash="test-hash", is_email_verified=True)
    db_session.add(user)
    await db_session.flush()
    project = Project(title="Upload integration", owner_id=user.id)
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    storage_root = tmp_path / "object-storage"
    monkeypatch.setattr(main, "create_object_storage", lambda _settings: LocalObjectStorage(storage_root))
    upload = UploadFile(
        filename="real-source.mp4",
        file=BytesIO(video_bytes),
        headers=Headers({"content-type": "video/mp4"}),
    )

    result = await main.upload_project_video(project.id, upload, db_session, project)

    asset = await db_session.get(Asset, result["asset"]["id"])
    assert asset is not None
    assert asset.checksum_sha256 == hashlib.sha256(video_bytes).hexdigest()
    assert asset.size_bytes == len(video_bytes)
    assert asset.duration_seconds == pytest.approx(2, abs=0.15)
    stored = storage_root / asset.object_key
    assert stored.is_file()
    assert stored.read_bytes() == video_bytes

    version = await db_session.get(TimelineVersion, result["timeline"]["version_id"])
    assert version is not None
    assert len(version.timeline_json["clips"]) == 1
    assert version.timeline_json["clips"][0]["asset_id"] == str(asset.id)
    reference = await db_session.scalar(
        __import__("sqlalchemy").select(TimelineAssetReference).where(
            TimelineAssetReference.timeline_version_id == version.id,
            TimelineAssetReference.asset_id == asset.id,
        )
    )
    assert reference is not None


@pytest.mark.asyncio
async def test_upload_rejects_mismatched_mime_and_extension(db_session):
    user = User(email="upload-reject@example.com", password_hash="test-hash", is_email_verified=True)
    db_session.add(user)
    await db_session.flush()
    project = Project(title="Upload rejection", owner_id=user.id)
    db_session.add(project)
    await db_session.commit()

    upload = UploadFile(
        filename="payload.txt",
        file=BytesIO(b"not a video"),
        headers=Headers({"content-type": "text/plain"}),
    )
    with pytest.raises(HTTPException) as error:
        await main.upload_project_video(project.id, upload, db_session, project)
    assert error.value.status_code == 415
