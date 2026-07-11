"""Tests for the process-wide per-score lock (`nota.orchestrator.locks`)."""

from __future__ import annotations

import threading
import time

import pytest

from nota.orchestrator import locks


def test_score_lock_serializes_access_to_the_same_score():
    order: list[str] = []

    def worker(tag: str, hold_seconds: float):
        with locks.score_lock("score-a", timeout=5.0):
            order.append(f"{tag}-start")
            time.sleep(hold_seconds)
            order.append(f"{tag}-end")

    t1 = threading.Thread(target=worker, args=("first", 0.2))
    t1.start()
    time.sleep(0.05)  # ensure t1 grabs the lock first
    t2 = threading.Thread(target=worker, args=("second", 0.0))
    t2.start()
    t1.join()
    t2.join()

    assert order == ["first-start", "first-end", "second-start", "second-end"]


def test_score_lock_raises_lock_timeout_when_contended():
    holder_ready = threading.Event()
    release_holder = threading.Event()

    def holder():
        with locks.score_lock("score-b", timeout=5.0):
            holder_ready.set()
            release_holder.wait(timeout=5.0)

    t = threading.Thread(target=holder)
    t.start()
    holder_ready.wait(timeout=5.0)

    try:
        with pytest.raises(locks.LockTimeout):
            with locks.score_lock("score-b", timeout=0.2):
                pass
    finally:
        release_holder.set()
        t.join()


def test_score_lock_is_reusable_after_release():
    with locks.score_lock("score-c", timeout=5.0):
        pass
    # A second acquisition after the first released should not time out.
    with locks.score_lock("score-c", timeout=0.5):
        pass


def test_different_scores_do_not_contend():
    release_holder = threading.Event()
    holder_ready = threading.Event()

    def holder():
        with locks.score_lock("score-d-1", timeout=5.0):
            holder_ready.set()
            release_holder.wait(timeout=5.0)

    t = threading.Thread(target=holder)
    t.start()
    holder_ready.wait(timeout=5.0)

    try:
        # A different score_id must not be blocked by score-d-1's holder.
        with locks.score_lock("score-d-2", timeout=0.5):
            pass
    finally:
        release_holder.set()
        t.join()
