"""Tests for the external-target config shim and its wiring.

The shim is what lets a siege point at an *arbitrary* external agent: the
endpoint resolves from flag-or-env (flag wins), and auth headers come from the
env only so a token never reaches the command line. These tests pin that
contract plus the adapter/CLI seams that consume it.
"""
from __future__ import annotations

from pathlib import Path

from coehoorn.agent_adapter import HttpAgentAdapter
from coehoorn.cli import main
from coehoorn.config import headers_from_env, resolve_endpoint

REPO_ROOT = Path(__file__).resolve().parent.parent
RUBRIC = str(REPO_ROOT / "examples" / "rubric_coach.yaml")


# --------------------------------------------------------------------------- #
# resolve_endpoint
# --------------------------------------------------------------------------- #
def test_flag_wins_over_env():
    env = {"AGENT_ENDPOINT": "http://from-env/chat"}
    assert resolve_endpoint("http://from-flag/chat", env) == "http://from-flag/chat"


def test_env_fallback_primary_var():
    assert resolve_endpoint(None, {"AGENT_ENDPOINT": "http://x/chat"}) == "http://x/chat"


def test_env_fallback_alias_var():
    assert (
        resolve_endpoint(None, {"COEHOORN_AGENT_ENDPOINT": "http://y/chat"})
        == "http://y/chat"
    )


def test_primary_var_beats_alias():
    env = {"AGENT_ENDPOINT": "http://a", "COEHOORN_AGENT_ENDPOINT": "http://b"}
    assert resolve_endpoint(None, env) == "http://a"


def test_none_when_nothing_configured():
    assert resolve_endpoint(None, {}) is None


def test_blank_env_value_is_not_an_endpoint():
    assert resolve_endpoint(None, {"AGENT_ENDPOINT": "   "}) is None


# --------------------------------------------------------------------------- #
# headers_from_env
# --------------------------------------------------------------------------- #
def test_no_headers_by_default():
    assert headers_from_env({}) == {}


def test_raw_auth_header_any_name():
    headers = headers_from_env({"AGENT_AUTH_HEADER": "x-api-key: secret-123"})
    assert headers == {"x-api-key": "secret-123"}


def test_api_key_maps_to_bearer():
    assert headers_from_env({"AGENT_API_KEY": "sk-abc"}) == {
        "Authorization": "Bearer sk-abc"
    }


def test_raw_authorization_header_not_overwritten_by_api_key():
    env = {
        "AGENT_AUTH_HEADER": "Authorization: Token raw-wins",
        "AGENT_API_KEY": "sk-should-be-ignored",
    }
    assert headers_from_env(env) == {"Authorization": "Token raw-wins"}


def test_malformed_auth_header_without_colon_is_ignored():
    assert headers_from_env({"AGENT_AUTH_HEADER": "no-colon-here"}) == {}


# --------------------------------------------------------------------------- #
# HttpAgentAdapter carries the headers to the wire (and stays bytewise-clean
# without them).
# --------------------------------------------------------------------------- #
class _CapturingResp:
    def raise_for_status(self) -> None: ...

    def json(self) -> dict:
        return {"reply": "ok"}


class _CapturingClient:
    def __init__(self) -> None:
        self.last_kwargs: dict | None = None
        self.closed = False

    async def post(self, url, **kwargs) -> _CapturingResp:
        self.last_kwargs = {"url": url, **kwargs}
        return _CapturingResp()

    async def aclose(self) -> None:
        self.closed = True


async def test_adapter_sends_auth_headers_when_set():
    client = _CapturingClient()
    adapter = HttpAgentAdapter(
        "http://target/chat", client=client, headers={"Authorization": "Bearer t"}
    )
    assert await adapter([{"role": "user", "content": "hi"}]) == "ok"
    assert client.last_kwargs["headers"] == {"Authorization": "Bearer t"}
    assert client.last_kwargs["json"] == {"conversation": [{"role": "user", "content": "hi"}]}


async def test_adapter_omits_headers_kwarg_when_none():
    # Backwards-compat: with no headers, `post` is called with json only —
    # exactly as the local-stub path always has.
    client = _CapturingClient()
    adapter = HttpAgentAdapter("http://target/chat", client=client)
    await adapter([{"role": "user", "content": "hi"}])
    assert "headers" not in client.last_kwargs


# --------------------------------------------------------------------------- #
# CLI: a clean exit-2 error when no endpoint is resolvable (no flag, no env).
# --------------------------------------------------------------------------- #
def test_run_clean_error_without_endpoint(monkeypatch, capsys):
    monkeypatch.delenv("AGENT_ENDPOINT", raising=False)
    monkeypatch.delenv("COEHOORN_AGENT_ENDPOINT", raising=False)
    rc = main(["run", "--rubric", RUBRIC])
    assert rc == 2
    err = capsys.readouterr().err.lower()
    assert "agent_endpoint" in err


def test_run_accepts_endpoint_from_env(monkeypatch):
    # The parser no longer requires --agent; the env var alone satisfies it.
    # (We assert resolution here, not a live run — the network call is mocked
    #  out by stopping before it via a bogus rubric path is *not* used; instead
    #  we verify resolve_endpoint reads the env the CLI consults.)
    monkeypatch.setenv("AGENT_ENDPOINT", "http://ci-target/chat")
    assert resolve_endpoint(None) == "http://ci-target/chat"
