import asyncio

import pytest

from app.render_engine import RenderPlan
from app.render_executor import RenderExecutionError, execute_ffmpeg_plan, verify_output_decode


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


@pytest.mark.asyncio
async def test_executor_kills_ffmpeg_when_task_is_cancelled(monkeypatch):
    started = asyncio.Event()
    killed = asyncio.Event()

    class BlockingProcess:
        returncode = -9
        async def communicate(self):
            started.set()
            await killed.wait()
            return b"", b""
        def kill(self):
            killed.set()

    async def fake_create(*argv, **kwargs):
        return BlockingProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create)
    task = asyncio.create_task(execute_ffmpeg_plan(_plan()))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert killed.is_set()


@pytest.mark.asyncio
async def test_decode_verification_uses_strict_ffmpeg_decode_flags(monkeypatch):
    process = FakeProcess()
    captured = {}

    async def fake_create(*argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create)
    await verify_output_decode("/tmp/output.mp4", timeout_seconds=10)
    assert "-xerror" in captured["argv"]
    assert "-err_detect" in captured["argv"]
    assert "explode" in captured["argv"]
    assert captured["argv"][-3:] == ("-f", "null", "-")
    assert captured["kwargs"]["stdin"] == asyncio.subprocess.DEVNULL


@pytest.mark.asyncio
async def test_decode_verification_rejects_nonzero_exit(monkeypatch):
    async def fake_create(*argv, **kwargs):
        return FakeProcess(returncode=1, stderr=b"corrupt decoded frame")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create)
    with pytest.raises(RenderExecutionError, match="corrupt decoded frame"):
        await verify_output_decode("/tmp/output.mp4", timeout_seconds=10)


@pytest.mark.asyncio
async def test_decode_verification_kills_ffmpeg_on_timeout(monkeypatch):
    class BlockingProcess:
        returncode = -9
        def __init__(self):
            self.killed = False
        async def communicate(self):
            await asyncio.Event().wait()
            return b"", b""
        def kill(self):
            self.killed = True

    process = BlockingProcess()

    async def fake_create(*argv, **kwargs):
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create)
    with pytest.raises(RenderExecutionError, match="decode verification exceeded"):
        await verify_output_decode("/tmp/output.mp4", timeout_seconds=1)
    assert process.killed is True


@pytest.mark.asyncio
async def test_decode_verification_kills_ffmpeg_on_cancellation(monkeypatch):
    started = asyncio.Event()
    killed = asyncio.Event()

    class BlockingProcess:
        returncode = -9
        async def communicate(self):
            started.set()
            await killed.wait()
            return b"", b""
        def kill(self):
            killed.set()

    process = BlockingProcess()

    async def fake_create(*argv, **kwargs):
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create)
    task = asyncio.create_task(verify_output_decode("/tmp/output.mp4"))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert killed.is_set()
