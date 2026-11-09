import asyncio

import pytest

from app.render_engine import RenderPlan
from app.render_executor import RenderExecutionError, execute_ffmpeg_plan


class FakeProcess:
    def __init__(self, returncode=0, stderr=b"rendered"):
        self.returncode = returncode
        self.stderr = stderr
        self.killed = False

    async def communicate(self):
        return b"", self.stderr

    def kill(self):
        self.killed = True


def _plan():
    return RenderPlan(
        argv=("ffmpeg", "-version"),
        output_path="/tmp/render.mp4",
        duration_seconds=2,
        input_asset_ids=("asset-1",),
        includes_audio=False,
    )


@pytest.mark.asyncio
async def test_executor_runs_ffmpeg_without_shell_and_checks_output(monkeypatch):
    process = FakeProcess()
    captured = {}

    async def fake_create(*argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create)
    monkeypatch.setattr("app.render_executor.os.path.getsize", lambda path: 123)

    result = await execute_ffmpeg_plan(_plan(), timeout_seconds=10)

    assert captured["argv"] == ("ffmpeg", "-version")
    assert captured["kwargs"]["stdin"] == asyncio.subprocess.DEVNULL
    assert result.output_path == "/tmp/render.mp4"
    assert result.stderr_tail == "rendered"


@pytest.mark.asyncio
async def test_executor_rejects_nonzero_ffmpeg_exit(monkeypatch):
    async def fake_create(*argv, **kwargs):
        return FakeProcess(returncode=7, stderr=b"encoder failed")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create)

    with pytest.raises(RenderExecutionError, match="encoder failed"):
        await execute_ffmpeg_plan(_plan())


@pytest.mark.asyncio
async def test_executor_rejects_missing_output(monkeypatch):
    async def fake_create(*argv, **kwargs):
        return FakeProcess()

    def missing_file(_path):
        raise FileNotFoundError("missing")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create)
    monkeypatch.setattr("app.render_executor.os.path.getsize", missing_file)

    with pytest.raises(RenderExecutionError, match="output file is missing"):
        await execute_ffmpeg_plan(_plan())
