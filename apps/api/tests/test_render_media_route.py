from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.testclient import TestClient

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


def test_render_media_route_supports_http_range_requests(tmp_path, monkeypatch):
    project_id, job_id = uuid4(), uuid4()
    source = tmp_path / "render.mp4"
    source.write_bytes(b"0123456789abcdef")
    storage = LocalObjectStorage(tmp_path / "objects")
    storage.put_file(source, "renders/project/job.mp4")
    job = SimpleNamespace(status="succeeded", output_object_key="renders/project/job.mp4")

    async def override_db():
        return FakeDB(job)

    monkeypatch.setattr(main, "create_object_storage", lambda settings: storage)
    main.app.dependency_overrides[main.get_db] = override_db
    main.app.dependency_overrides[main.require_owned_project] = lambda: SimpleNamespace(id=project_id)
    try:
        with TestClient(main.app) as client:
            response = client.get(
                f"/v1/projects/{project_id}/renders/{job_id}/media",
                headers={"Range": "bytes=4-7"},
            )
        assert response.status_code == 206
        assert response.headers["content-range"] == "bytes 4-7/16"
        assert response.content == b"4567"
    finally:
        main.app.dependency_overrides.pop(main.get_db, None)
        main.app.dependency_overrides.pop(main.require_owned_project, None)
