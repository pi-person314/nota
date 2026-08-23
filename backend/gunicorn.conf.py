"""Gunicorn configuration for the production entrypoint (`wsgi:app`).

Run with: gunicorn -c gunicorn.conf.py wsgi:app
"""

import os

bind = "0.0.0.0:" + os.environ.get("PORT", "5001")

# workers = 1 is a correctness constraint, not a tuning default — do not
# raise it without redesigning the pieces of this app that assume a single
# process:
#   - Concurrent score edits are guarded by in-process threading locks,
#     which only serialize access within one process.
#   - The parsed-score cache lives in process memory, so a second worker
#     would see a cold, inconsistent cache and could disagree with the
#     first about a score's current state.
#   - The MCP tool server is started as a per-process subprocess; a second
#     worker means a second subprocess independently touching the same
#     score files.
# Any of these can corrupt scores if more than one worker process is
# handling requests. Scale this app by threads (below), not workers.
workers = 1

# Concurrency within the single worker process. Request handling here is
# largely I/O-bound (DB, filesystem, subprocess/LLM calls), so threads scale
# it without the multi-process pitfalls above.
threads = int(os.environ.get("GUNICORN_THREADS", "16"))

# Generous timeout: command loops and OMR (optical music recognition) runs
# can legitimately take a long time to finish.
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "300"))
