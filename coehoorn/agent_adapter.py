"""Target-agent adapters.

An adapter is any async callable taking a conversation (list of
{role, content} dicts in OpenAI/Anthropic chat shape) and returning the
agent's next assistant reply as a string. The default adapter speaks the
Coehoorn local stub's wire format (POST {conversation} -> {reply}).
"""
from __future__ import annotations

from typing import Awaitable, Callable, Protocol

import httpx

AgentCall = Callable[[list[dict]], Awaitable[str]]


class AgentReply(str):
    """An agent reply that also carries any tool calls the agent made.

    It *is* a ``str`` (the reply text), so every existing code path that treats
    a reply as text keeps working unchanged; the conversation runner reads the
    extra ``.tool_calls`` when present. Plain chat agents just return a ``str``.
    """

    tool_calls: list[dict]

    def __new__(cls, content: str, tool_calls: list[dict] | None = None) -> "AgentReply":
        obj = super().__new__(cls, content)
        obj.tool_calls = list(tool_calls or [])
        return obj


class AgentAdapter(Protocol):
    async def __call__(self, conversation: list[dict]) -> str: ...


class HttpAgentAdapter:
    """POSTs {conversation: [...]} to a chat endpoint and returns reply.

    One owned ``AsyncClient`` is created lazily and reused across every turn
    (one connection pool for the whole conversation, not one per turn). Close
    it with ``await adapter.aclose()`` or use it as an async context manager;
    an injected client is the caller's to close.
    """

    def __init__(
        self,
        endpoint: str,
        timeout: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.timeout = timeout
        self._client = client
        self._owns_client = client is None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def __call__(self, conversation: list[dict]) -> str:
        resp = await self._get_client().post(
            self.endpoint, json={"conversation": conversation}
        )
        resp.raise_for_status()
        data = resp.json()
        reply = data.get("reply")
        if not isinstance(reply, str):
            raise ValueError(
                f"Agent response missing string 'reply' field: keys={list(data.keys())}"
            )
        # An agent may also report the tools it invoked, in OpenAI/Anthropic
        # shape; surface them so tool-policy criteria can be judged.
        tool_calls = data.get("tool_calls")
        if tool_calls:
            return AgentReply(reply, tool_calls=tool_calls)
        return reply

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> HttpAgentAdapter:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()


class CallableAdapter:
    """Wrap an in-process callable for tests and fixtures."""

    def __init__(self, fn: Callable[[list[dict]], str]) -> None:
        self._fn = fn

    async def __call__(self, conversation: list[dict]) -> str:
        return self._fn(conversation)
