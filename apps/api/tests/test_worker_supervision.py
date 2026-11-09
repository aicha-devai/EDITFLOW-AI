import asyncio
import pytest

from app.rendering import RenderCancelled
from app.worker_main import _run_with_lease


@pytest.mark.asyncio
async def test_lease_cancellation_stops_render_task():
    render_started = asyncio.Event()
    render_stopped = asyncio.Event()

    async def render():
        render_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            render_stopped.set()

    async def heartbeat():
        await render_started.wait()
        raise RenderCancelled("cancel requested")

    with pytest.raises(RenderCancelled):
        await _run_with_lease(render(), heartbeat())
    assert render_stopped.is_set()


@pytest.mark.asyncio
async def test_render_completion_cancels_heartbeat():
    heartbeat_stopped = asyncio.Event()

    async def render():
        return "done"

    async def heartbeat():
        try:
            await asyncio.Event().wait()
        finally:
            heartbeat_stopped.set()

    assert await _run_with_lease(render(), heartbeat()) == "done"
    assert heartbeat_stopped.is_set()
