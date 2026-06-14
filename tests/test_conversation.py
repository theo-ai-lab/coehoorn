"""Tests for the conversation runner — heuristic mode only.

LLM mode needs a network call and an API key; covered by integration smoke
tests when credentials are available, not by unit tests.
"""
import pytest

from coehoorn.agent_adapter import CallableAdapter
from coehoorn.conversation import (
    run_conversation_heuristic,
    run_conversations,
)
from coehoorn.personas import generate_personas_heuristic
from coehoorn.schemas import Archetype, Persona


def _echo_agent():
    def _reply(conversation):
        last_user = next(
            (m["content"] for m in reversed(conversation) if m["role"] == "user"),
            "",
        )
        return f"agent reply to: {last_user[:30]}"

    return CallableAdapter(_reply)


@pytest.mark.asyncio
async def test_heuristic_runner_alternates_user_assistant():
    persona = Persona(id="p00", archetype=Archetype.EMOTIONAL, name="Casey", description="d")
    t = await run_conversation_heuristic(persona, _echo_agent(), max_turns=3)
    assert len(t.turns) == 6  # 3 user + 3 assistant
    assert [tu.role for tu in t.turns] == ["user", "assistant"] * 3
    assert [tu.index for tu in t.turns] == [0, 1, 2, 3, 4, 5]


@pytest.mark.asyncio
async def test_heuristic_runner_uses_archetype_specific_probe():
    persona = Persona(id="p00", archetype=Archetype.EMOTIONAL, name="Casey", description="d")
    t = await run_conversation_heuristic(persona, _echo_agent(), max_turns=2)
    user_messages = [tu.content for tu in t.turns if tu.role == "user"]
    # Emotional archetype's second probe contains escalation language.
    assert any("end my life" in m or "want to end" in m or "hard time" in m for m in user_messages)


@pytest.mark.asyncio
async def test_run_conversations_returns_one_transcript_per_persona():
    personas = generate_personas_heuristic(n=4)
    transcripts = await run_conversations(
        personas, _echo_agent(), max_turns=2, mode="heuristic", concurrency=2
    )
    assert len(transcripts) == 4
    assert {t.persona.id for t in transcripts} == {p.id for p in personas}


@pytest.mark.asyncio
async def test_run_conversations_rejects_unknown_mode():
    personas = generate_personas_heuristic(n=1)
    with pytest.raises(ValueError, match="unknown mode"):
        await run_conversations(
            personas, _echo_agent(), max_turns=1, mode="invalid"
        )


@pytest.mark.asyncio
async def test_llm_mode_requires_rubric():
    personas = generate_personas_heuristic(n=1)
    with pytest.raises(ValueError, match="rubric"):
        await run_conversations(
            personas, _echo_agent(), max_turns=1, mode="llm", rubric=None
        )
