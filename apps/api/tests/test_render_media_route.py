from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.responses import FileResponse, RedirectResponse

from app import main
from app.storage import LocalObjectStorage, S3ObjectStorage


class FakeDB:
    def __init__(self, job):
        self.job = job

    async def scalar(self, statement):
        return self.job


class FakeS3Client:
    def generate_presigned_url(self, operation, Params, ExpiresIn):
        assert operation == "get_object"
        assert Params["Key"] == "renders/project/job.mp4"
        assert ExpiresIn == 900
        return "https://storage.example/signed-render.mp4"


@pytest.mark.asyncio
async def test_render_media_route_serves_local_mp4(tmp_path, monkeypatch):
    project_id, job_id = uuid4(), uuid4()
    source = tmp_path / "render.mp4"
    source.write_bytes(b"rendered-mp4")
    storage = LocalObjectStorage(tmp_path / "objects")
    storage.put_file(source, "renders/project/job.mp4")
    job = SimpleNamespace(status="succeeded", output_object_key="renders/project/job.mp4")
    monkeypatch.setattr(main, "create_object_storage", lambda settings: storage)

    response = await main.stream_project_render_media(project_id, job_id, FakeDB(job))

    assert isinstance(response, FileResponse)
    assert Path(response.path).read_bytes() == b"rendered-mp4"
    assert response.media_type == "video/mp4"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["accept-ranges"] == "bytes"


@pytest.mark.asyncio
async def test_render_media_route_redirects_to_expiring_s3_url(monkeypatch):
    project_id, job_id = uuid4(), uuid4()
    storage = S3ObjectStorage(bucket="editflow-media", client=FakeS3Client())
    job = SimpleNamespace(status="succeeded", output_object_key="renders/project/job.mp4")
    monkeypatch.setattr(main, "create_object_storage", lambda settings: storage)

    response = await main.stream_project_render_media(project_id, job_id, FakeDB(job))

    assert isinstance(response, RedirectResponse)
    assert response.status_code == 307
    assert response.headers["location"] == "https://storage.example/signed-render.mp4"


@pytest.mark.asyncio
async def test_render_media_route_rejects_unfinished_jobs():
    project_id, job_id = uuid4(), uuid4()
    job = SimpleNamespace(status="running", output_object_key=None)

    with pytest.raises(HTTPException) as exc:
        await main.stream_project_render_media(project_id, job_id, FakeDB(job))

    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_render_media_route_rejects_missing_jobs():
    with pytest.raises(HTTPException) as exc:
        await main.stream_project_render_media(uuid4(), uuid4(), FakeDB(None))

    assert exc.value.status_code == 404
