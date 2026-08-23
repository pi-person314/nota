"""Per-user daily usage quotas on the LLM-backed endpoints (voice/text
commands and transcription), protecting server API spend now that signup
is public.

The quota is an abuse guard, not a billing mechanism: once a request is
allowed, its unit of quota is spent immediately, before the caller does the
actual (expensive) work. If that downstream call then fails, the spent
unit is not refunded -- a retry costs another unit, the same as any other
request. This keeps the accounting simple and race-free; it deliberately
does not try to be a precise ledger of successful API calls.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError

from . import db as db_module
from . import models

# Fallback limits, used whenever the corresponding environment variable is
# unset or not a valid integer.
DEFAULT_LIMITS = {"command": 200, "transcribe": 400}

# Env var read at call time (not import time) for each kind, mirroring the
# pattern `OMR_TIMEOUT_S` uses in services/omr.py -- lets an operator adjust
# a limit without a process restart tied to import order.
_LIMIT_ENV_VARS = {
    "command": "DAILY_COMMAND_LIMIT",
    "transcribe": "DAILY_TRANSCRIBE_LIMIT",
}


@dataclass
class QuotaDecision:
    """Outcome of a `check_and_increment` call.

    `used` is the post-increment count for the day when `allowed` is True
    (i.e. it includes the request just spent); when `allowed` is False it
    is the count at time of denial, which was left unchanged.
    """

    allowed: bool
    limit: int
    used: int


def _limit_for(kind: str) -> int:
    """Resolve today's configured limit for `kind`. A value <= 0 (set
    explicitly via the environment) disables the limit for that kind
    entirely -- every call to `check_and_increment` for it is allowed
    without ever touching the database.
    """
    env_var = _LIMIT_ENV_VARS[kind]
    raw = os.environ.get(env_var)
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass
    return DEFAULT_LIMITS[kind]


def _today() -> str:
    """Today's date as a UTC "YYYY-MM-DD" string -- see `models.UsageCounter`
    for why UTC (not server-local time) is used for the reset boundary.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def check_and_increment(user_id: str, kind: str) -> QuotaDecision:
    """Check `user_id`'s usage counter for `kind` today against its daily
    limit, and atomically increment it if the request is allowed.

    A denied request does not consume any quota -- the counter is left
    untouched. Disabling a limit (env var <= 0) skips the database
    entirely and always allows.

    The app runs single-process, multi-threaded, so the only concurrency
    hazard here is two request threads racing to create the same
    (user_id, day, kind) counter row on the first request of the day for
    that combination. That race is handled by catching the resulting
    unique-constraint violation and retrying the whole read-modify path
    once, which is sufficient at this scale -- there is no multi-process
    contention to worry about.
    """
    limit = _limit_for(kind)
    if limit <= 0:
        return QuotaDecision(allowed=True, limit=limit, used=0)

    day = _today()

    for _attempt in range(2):
        try:
            with db_module.session_scope() as session:
                row = (
                    session.query(models.UsageCounter)
                    .filter_by(user_id=user_id, day=day, kind=kind)
                    .one_or_none()
                )
                if row is None:
                    row = models.UsageCounter(user_id=user_id, day=day, kind=kind, count=0)
                    session.add(row)
                    # Force the INSERT now so a racing thread's conflicting
                    # insert surfaces here as an IntegrityError, inside this
                    # try block, rather than silently at the outer commit.
                    session.flush()

                if row.count >= limit:
                    return QuotaDecision(allowed=False, limit=limit, used=row.count)

                row.count += 1
                return QuotaDecision(allowed=True, limit=limit, used=row.count)
        except IntegrityError:
            # Another thread won the race to insert today's first counter
            # row for this (user, kind); its row exists now, so retrying
            # takes the plain read-modify path instead of inserting again.
            continue

    raise RuntimeError(
        f"quota: could not reconcile usage counter for user={user_id!r} kind={kind!r}"
    )
