"""Run async SDK calls (ring_doorbell, blinkpy) from the threaded web server.

Both vendor libraries are asyncio based, while the web server is a plain
threaded ``http.server``. One background event loop is shared by all
providers and blocking callers wait on it with a timeout.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any, Awaitable, Optional

_loop: Optional[asyncio.AbstractEventLoop] = None
_lock = threading.Lock()


def _ensure_loop() -> asyncio.AbstractEventLoop:
    global _loop
    with _lock:
        if _loop is None:
            _loop = asyncio.new_event_loop()
            t = threading.Thread(target=_loop.run_forever, name="homehub-async", daemon=True)
            t.start()
        return _loop


def run(coro: Awaitable[Any], timeout: float = 30.0) -> Any:
    """Run ``coro`` on the shared loop and wait for its result."""
    fut = asyncio.run_coroutine_threadsafe(coro, _ensure_loop())  # type: ignore[arg-type]
    return fut.result(timeout)
