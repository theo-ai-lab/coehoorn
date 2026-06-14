"""Tests for the target-agent adapters — the network boundary.

The HTTP adapter must reuse a single client across a conversation's turns
(not open a fresh connection per turn), close the client it owns, and leave an
injected client for its caller to close.
"""
from __future__ import annotations

import httpx
import pytest

from coehoorn.agent_adapter import CallableAdapter, HttpAgentAdapter


class _FakeResp:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    count = 0  # how many clients have been constructed

    def __init__(self, **kwargs) -> None:
        _FakeClient.count += 1
        self.closed = False
        self.posts = 0
        self.payload = {"reply": "ok"}

    async def post(self, url, json) -> _FakeResp:
        self.posts += 1
        return _FakeResp(self.payload)

    async def aclose(self) -> None:
        self.closed = True


async def test_owned_client_is_reused_across_turns_and_closed(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)
    _FakeClient.count = 0
    async with HttpAgentAdapter("http://127.0.0.1:8001/chat") as adapter:
        assert await adapter([{"role": "user", "content": "a"}]) == "ok"
        client = adapter._client
        assert await adapter([{"role": "user", "content": "b"}]) == "ok"
        assert adapter._client is client  # same client across turns
    assert client.closed is True  # closed on context exit
    assert client.posts == 2
    assert _FakeClient.count == 1  # exactly one client for the whole conversation


async def test_injected_client_is_not_closed(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)
    injected = _FakeClient()
    _FakeClient.count = 0  # reset after constructing the injected one
    adapter = HttpAgentAdapter("http://127.0.0.1:8001/chat", client=injected)
    await adapter([{"role": "user", "content": "a"}])
    await adapter.aclose()
    assert injected.closed is False  # the caller owns an injected client
    assert _FakeClient.count == 0  # no new client was created


async def test_missing_reply_field_raises():
    bad = _FakeClient()
    bad.payload = {"oops": 1}
    adapter = HttpAgentAdapter("http://127.0.0.1:8001/chat", client=bad)
    with pytest.raises(ValueError):
        await adapter([{"role": "user", "content": "a"}])


async def test_callable_adapter_passes_conversation():
    adapter = CallableAdapter(lambda conv: f"got {len(conv)}")
    assert await adapter([{"role": "user", "content": "x"}]) == "got 1"
