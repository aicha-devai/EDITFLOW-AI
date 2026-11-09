# Render worker supervision

The polling worker supervises the render coroutine and lease-heartbeat coroutine as a pair. If the heartbeat exits with a lost lease or a cancellation request, the worker cancels the render task rather than allowing an encoder to continue under an invalid lease. The FFmpeg executor handles task cancellation by killing and reaping its subprocess before propagating cancellation. Normal render completion cancels the heartbeat task.

This is cooperative cancellation at the worker/process boundary. A worker host crash still relies on lease expiry and subsequent reclaim; it is not an immediate distributed process kill. The database cancellation flag remains authoritative, and claim-time validation closes cancelled queued/reclaimed work.
