"""Resolve the external target endpoint and auth headers from flags/env.

This is the small config shim that lets a siege point at an *arbitrary*
external agent — not just the bundled local stub — without hardcoding
anything. It is the additive seam behind the "siege a real external agent"
use: the wire contract (POST ``{conversation: [...]}`` -> ``{reply: "..."}``)
is unchanged, but *where* you point and *how* you authenticate are now
first-class and CI-friendly.

Resolution order for the endpoint:

1. the explicit ``--agent`` flag (always wins; keeps every existing
   invocation working byte-for-byte),
2. then ``AGENT_ENDPOINT`` / ``COEHOORN_AGENT_ENDPOINT`` from the
   environment (set one from a GitHub Actions secret or repo variable).

Auth headers are read from the environment *only*, never a flag, so a bearer
token never lands in a process listing, a shell history, or a committed
command line:

* ``AGENT_AUTH_HEADER`` — a raw header line, the most general form. Supports
  any header name a real agent expects, e.g.
  ``Authorization: Bearer sk-...`` or ``x-api-key: ...``.
* ``AGENT_API_KEY`` — convenience: mapped to ``Authorization: Bearer <key>``
  unless ``AGENT_AUTH_HEADER`` already set an ``Authorization`` header.

NOTE: ``AGENT_API_KEY`` authenticates Coehoorn *to the target agent*. It is
distinct from ``ANTHROPIC_API_KEY``, which powers Coehoorn's own LLM-mode
personas and judge. A live siege of a real agent in LLM mode needs both — and
choosing a real endpoint + supplying those keys is the deliberately
un-fakeable part of the engagement (see ``docs/ENGAGEMENT_TEMPLATE.md``).
"""
from __future__ import annotations

import os
from collections.abc import Mapping

#: Environment variables consulted for the target endpoint, in priority order.
ENDPOINT_ENV_VARS: tuple[str, ...] = ("AGENT_ENDPOINT", "COEHOORN_AGENT_ENDPOINT")


def resolve_endpoint(
    flag_value: str | None,
    env: Mapping[str, str] | None = None,
) -> str | None:
    """Return the target endpoint from the flag, else the environment, else None.

    The explicit flag always wins so existing ``--agent URL`` calls are
    unaffected; an env var is the fallback CI uses to inject a secret/variable.
    """
    if flag_value:
        return flag_value
    src = os.environ if env is None else env
    for name in ENDPOINT_ENV_VARS:
        value = src.get(name)
        if value:
            return value.strip() or None
    return None


def headers_from_env(env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Build request headers for authenticating to the target agent.

    Returns an empty dict when nothing is configured (the common local-stub
    case), so the adapter sends exactly what it always has.
    """
    src = os.environ if env is None else env
    headers: dict[str, str] = {}

    raw = src.get("AGENT_AUTH_HEADER")
    if raw and ":" in raw:
        name, _, value = raw.partition(":")
        name, value = name.strip(), value.strip()
        if name and value:
            headers[name] = value

    api_key = src.get("AGENT_API_KEY")
    if api_key and not any(k.lower() == "authorization" for k in headers):
        headers["Authorization"] = f"Bearer {api_key.strip()}"

    return headers
