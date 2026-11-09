from pathlib import Path

import pytest

from app.storage import S3ObjectStorage, StorageError


class FakeS3Client:
    def __init__(self):
        self.downloads = []
        self.uploads = []
        self.presigns = []

    def download_file(self, bucket, key, filename):
        self.downloads.append((bucket, key, filename))
        Path(filename).write_bytes(b"source-video")

    def upload_file(self, filename, bucket, key):
        self.uploads.append((filename, bucket, key))

    def generate_presigned_url(self, operation, Params, ExpiresIn):
        self.presigns.append((operation, Params, ExpiresIn))
        return "https://storage.example/signed-object"


def test_s3_storage_download_upload_and_signed_url(tmp_path):
    client = FakeS3Client()
    storage = S3ObjectStorage(bucket="editflow-media", client=client)

    downloaded = storage.materialize("uploads/source.mp4", tmp_path / "work" / "source.mp4")
    assert downloaded.read_bytes() == b"source-video"

    output = tmp_path / "render.mp4"
    output.write_bytes(b"rendered-output")
    assert storage.put_file(output, "renders/project/job.mp4") == "renders/project/job.mp4"

    signed = storage.create_download_url("renders/project/job.mp4", expires_seconds=300)
    assert signed == "https://storage.example/signed-object"
    assert client.downloads[0][:2] == ("editflow-media", "uploads/source.mp4")
    assert client.uploads[0][1:] == ("editflow-media", "renders/project/job.mp4")
    assert client.presigns[0][2] == 300


@pytest.mark.parametrize("key", ["../escape.mp4", "/absolute.mp4", "a/../../escape.mp4", "a\\b.mp4", ""])
def test_s3_storage_rejects_unsafe_keys(key):
    storage = S3ObjectStorage(bucket="editflow-media", client=FakeS3Client())
    with pytest.raises(StorageError):
        storage.create_download_url(key)
