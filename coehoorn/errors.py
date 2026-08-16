"""Classify a failed approach so the report can say *why* a wall was never tested.

A siege talks to someone else's agent over the wire, and wire calls fail. The
question a report has to answer honestly is which kind of failure it was,
because the three kinds mean different things to the reader:

* ``retryable`` — the target throttled or stumbled (429/503, a timeout, a
  dropped connection). Nothing was learned about the wall; run it again, and
  honour ``Retry-After`` when the target named one.
* ``caller_fault`` — the siege was pointed or authenticated wrong (401/404/400).
  Nothing was learned about the wall either, but retrying will not help; fix
  the endpoint or the credential.
* ``system`` — anything else, including a target that answered with a shape the
  adapter cannot read. A bug on one side or the other.

What none of them mean is "the wall held". Folding a wire failure into the pass
column is the one outcome this module exists to prevent.
"""
from __future__ import annotations

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from enum import StrEnum

import httpx

#: Status codes that mean "come back later", not "you asked wrongly".
_TRANSIENT_STATUSES = frozenset({408, 425, 429})


class ErrorClass(StrEnum):
    """Why an approach never produced a transcript. Three states, not a bool:
    a reader must be able to tell a throttled siege from a misaimed one."""

    RETRYABLE = "retryable"
    CALLER_FAULT = "caller_fault"
    SYSTEM = "system"


def parse_retry_after(value: str | None, *, now: datetime | None = None) -> float | None:
    """Seconds to wait per an HTTP ``Retry-After`` header, or None.

    Both wire forms are accepted (RFC 9110 §10.2.3): delay-seconds and an
    HTTP-date. An unparseable or past value yields None rather than an
    exception — a malformed header from the target must never be the reason a
    siege report fails to be written.
    """
    if value is None:
        return None
    raw = value.strip()
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - (now or datetime.now(UTC))).total_seconds())


def classify_error(exc: BaseException) -> tuple[ErrorClass, int | None, float | None]:
    """Return ``(class, status_code, retry_after_seconds)`` for a failed approach.

    ``status_code`` and ``retry_after_seconds`` are None when the wire never got
    far enough to carry them (a timeout has no status; most responses name no
    Retry-After). ``retry_after_seconds`` is additionally None on every class
    but ``retryable``, because that is the only class on which it means
    anything — and the only combination :class:`~coehoorn.schemas.ApproachError`
    will accept. The tuple this returns is always representable as a record.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status in _TRANSIENT_STATUSES or 500 <= status < 600:
            retry_after = parse_retry_after(exc.response.headers.get("Retry-After"))
            return ErrorClass.RETRYABLE, status, retry_after
        # A Retry-After on anything else is read and discarded on purpose.
        # Targets do send it there — GitHub's secondary rate limit and
        # Cloudflare both answer 403 with one — but "come back in 60s" is
        # false advice for a wrong credential or a wrong path, and
        # ApproachError refuses to record the pair at all. Deciding it here,
        # where the class is decided, is what keeps the classifier's output
        # always representable: a header the target chose must never be able
        # to raise a ValidationError out of the siege runner.
        if 400 <= status < 500:
            return ErrorClass.CALLER_FAULT, status, None
        return ErrorClass.SYSTEM, status, None
    # Timeouts and transport failures (connect refused, read error, protocol
    # error) are all "the wire, not the wall" — transient by convention.
    if isinstance(exc, httpx.TimeoutException | httpx.TransportError):
        return ErrorClass.RETRYABLE, None, None
    return ErrorClass.SYSTEM, None, None
