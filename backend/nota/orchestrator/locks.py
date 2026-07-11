"""Process-wide per-score locking so two commands against the same score
never run concurrently (the second would race on undo snapshots and the
live XML file). A single process-wide `threading.Lock` per score_id,
created on first use and kept for the process lifetime — cheap, and scores
are never removed from the dict, but a lock object is a handful of bytes so
this is not a meaningful leak for the expected number of distinct scores.

This is a threading lock, not a DB advisory lock, so it only protects a
single Flask process. Fine for the dev server / a single worker process;
a multi-worker deployment would need to move this to the database.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Iterator

DEFAULT_LOCK_TIMEOUT = 15.0

_guard = threading.Lock()
_locks: dict[str, threading.Lock] = {}


class LockTimeout(Exception):
    """Raised when a score's lock could not be acquired within the timeout
    because another command is already running against it.
    """

    def __init__(self, score_id: str):
        super().__init__(f"Timed out waiting for the lock on score {score_id}.")
        self.score_id = score_id


def _lock_for(score_id: str) -> threading.Lock:
    with _guard:
        lock = _locks.get(score_id)
        if lock is None:
            lock = threading.Lock()
            _locks[score_id] = lock
        return lock


@contextmanager
def score_lock(score_id: str, timeout: float = DEFAULT_LOCK_TIMEOUT) -> Iterator[None]:
    """Acquire the given score's lock for the duration of the `with` block.

    Raises `LockTimeout` if it can't be acquired within `timeout` seconds
    (default matches the 15s budget the /command endpoint uses to decide
    whether to return 409 COMMAND_IN_PROGRESS).
    """
    lock = _lock_for(score_id)
    acquired = lock.acquire(timeout=timeout)
    if not acquired:
        raise LockTimeout(score_id)
    try:
        yield
    finally:
        lock.release()
