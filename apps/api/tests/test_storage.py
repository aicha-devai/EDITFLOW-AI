from pathlib import Path

import pytest

from app.storage import LocalObjectStorage, StorageError


def test_local_storage_materializes_and_stores_files(tmp_path):
    storage = LocalObjectStorage(tmp_path / "objects")
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video-data")
    storage.put_file(source, "renders/project/job.mp4")

    target = storage.materialize("renders/project/job.mp4", tmp_path / "work" / "copy.mp4")
    assert target.read_bytes() == b"video-data"


@pytest.mark.parametrize("key", ["../escape.mp4", "/absolute.mp4", "folder/../../escape"])
def test_local_storage_rejects_path_traversal(tmp_path, key):
    storage = LocalObjectStorage(tmp_path / "objects")
    with pytest.raises(StorageError):
        storage.materialize(key, tmp_path / "out.mp4")


def test_local_storage_rejects_missing_object(tmp_path):
    storage = LocalObjectStorage(tmp_path / "objects")
    with pytest.raises(StorageError, match="does not exist"):
        storage.materialize("missing.mp4", tmp_path / "out.mp4")
