"""The falsifiable-invariant demo, as a test.

This is the 10-second proof of Coehoorn's core claim — a verdict you can't fake —
and it is also the snippet shown in the README. A failure verdict that cites no
turn is not discouraged by a prompt; it is structurally unrepresentable. The
schema raises before such a thing can enter a report.
"""
import pytest
from pydantic import ValidationError

from coehoorn.schemas import CriterionStatus, CriterionVerdict


def test_a_breach_that_cites_no_turn_cannot_be_built():
    with pytest.raises(ValidationError):
        # "This criterion failed" — but it points at no turn as evidence.
        CriterionVerdict(
            criterion_id="safe_handling_of_self_harm",
            status=CriterionStatus.FAIL,
            confidence=0.99,
            cited_turn_index=None,  # no evidence
            rationale="the agent did something bad, trust me",
        )


def test_a_pass_that_cites_a_breach_turn_cannot_be_built():
    with pytest.raises(ValidationError):
        # A "held" verdict has no business citing a breach turn.
        CriterionVerdict(
            criterion_id="safe_handling_of_self_harm",
            status=CriterionStatus.PASS,
            confidence=0.99,
            cited_turn_index=3,
            rationale="held, but also here's a turn",
        )
