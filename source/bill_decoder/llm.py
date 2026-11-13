"""Shared model-call helpers: rate limiting and retries."""
import logging
import os
import threading
import time
from typing import Callable, TypeVar

log = logging.getLogger("bill_decoder")
T = TypeVar("T")

# Free Gemini tier allows 15 requests/min; stay safely under it.
_MIN_INTERVAL = 60.0 / float(os.getenv("MAX_RPM", "12"))
_lock = threading.Lock()
_last_call = 0.0
_fallback_hook: Callable[[], bool] | None = None


def set_fallback(hook: Callable[[], bool] | None) -> None:
    """Register a function that switches to a backup API key; it returns True if it switched."""
    global _fallback_hook
    _fallback_hook = hook


def _throttle() -> None:
    global _last_call
    with _lock:
        wait = _last_call + _MIN_INTERVAL - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()


def retry_call(fn: Callable[[], T], attempts: int = 4) -> T:
    """Run a model call with throttling; retry rate limits / transient errors, fail fast on 4xx."""
    last: Exception | None = None
    for attempt in range(attempts):
        _throttle()
        try:
            return fn()
        except Exception as e:
            code = getattr(e, "code", None)
            if isinstance(code, int) and 400 <= code < 500 and code != 429:
                raise RuntimeError(f"model call rejected (not retrying): {e}") from e
            last = e
            if code == 429 and attempt >= 1 and _fallback_hook and _fallback_hook():
                log.warning("quota exhausted on the main key; switched to the fallback key")
                continue
            wait = 2 ** attempt * 3
            log.warning("model call failed (%s); retrying in %ss", e, wait)
            time.sleep(wait)
    raise RuntimeError(f"model call failed after retries: {last}")
