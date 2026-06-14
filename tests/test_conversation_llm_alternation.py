"""Regression test for the LLM-mode persona_history alternation invariant.

The Anthropic Messages API requires `messages` to:
- start with role "user", and
- strictly alternate user / assistant.

A prior bug in `run_conversation_llm` replaced the leading user prompt with
the model's assistant reply and then appended a fresh user turn each
iteration, producing two consecutive user roles starting from turn 2's API
call. This test captures every `messages=` payload sent to a mocked
AsyncAnthropic client and asserts the invariant directly. The mock keeps
the test offline — no network call, no API key required.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from coehoorn.agent_adapter import CallableAdapter
from coehoorn.conversation import run_conversation_llm
from coehoorn.schemas import Archetype, Criterion, Persona, Rubric


class _StubTextBlock:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _StubResponse:
    def __init__(self, text: str) -> None:
        self.content = [_StubTextBlock(text)]


@pytest.mark.asyncio
async def test_persona_history_strictly_alternates_starting_with_user(monkeypatch):
    captured: list[list[dict]] = []

    async def _fake_create(**kwargs):
        # Snapshot persona_history at call time — the production code mutates
        # it after the call returns, so we must copy now.
        captured.append([dict(m) for m in kwargs["messages"]])
        return _StubResponse("mock persona message")

    class _FakeAsyncAnthropic:
        def __init__(self, *_, **__) -> None:
            self.messages = MagicMock()
            self.messages.create = AsyncMock(side_effect=_fake_create)

    # The production code does `from anthropic import AsyncAnthropic` inside
    # the function body, so patching the module attribute is sufficient.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key-for-test")
    monkeypatch.setattr("anthropic.AsyncAnthropic", _FakeAsyncAnthropic)

    def _agent(_conversation: list[dict]) -> str:
        return "agent reply text"

    persona = Persona(
        id="p00", archetype=Archetype.EMOTIONAL, name="Tester", description="d"
    )
    rubric = Rubric(
        criteria=[Criterion(id="x", description="d")], overall_pass_threshold=1.0
    )

    transcript = await run_conversation_llm(
        persona, CallableAdapter(_agent), rubric=rubric, max_turns=3
    )

    assert len(captured) == 3, f"expected 3 LLM calls, got {len(captured)}"

    for i, messages in enumerate(captured):
        assert messages, f"call {i}: empty messages list"
        # First message must be user.
        assert messages[0]["role"] == "user", (
            f"call {i}: first message role must be 'user', got "
            f"{messages[0]['role']!r}; full roles={[m['role'] for m in messages]}"
        )
        # Strict alternation, no two consecutive same-role.
        for j in range(1, len(messages)):
            assert messages[j]["role"] != messages[j - 1]["role"], (
                f"call {i}: consecutive same-role at indices {j-1},{j}: "
                f"roles={[m['role'] for m in messages]}"
            )
        # All roles in the allowed set and content non-empty.
        for j, m in enumerate(messages):
            assert m["role"] in {"user", "assistant"}, (
                f"call {i}, msg {j}: bad role {m['role']!r}"
            )
            assert isinstance(m["content"], str) and m["content"], (
                f"call {i}, msg {j}: empty or non-string content {m['content']!r}"
            )
        # Per-call length invariant: call i is preceded by i completed
        # user/assistant pairs in persona_history, then one fresh user turn
        # is appended right before the API call. So call i has length 2*i + 1.
        assert len(messages) == 2 * i + 1, (
            f"call {i}: expected length {2 * i + 1}, got {len(messages)}; "
            f"roles={[m['role'] for m in messages]}"
        )

    # Final transcript shape: 3 user + 3 assistant = 6 turns.
    assert len(transcript.turns) == 6
    assert [t.role for t in transcript.turns] == [
        "user", "assistant"
    ] * 3
