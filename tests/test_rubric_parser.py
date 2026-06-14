from pathlib import Path

import pytest

from coehoorn.rubric_parser import parse_rubric_dict, parse_rubric_file


def test_parses_example_rubric():
    rubric, rules = parse_rubric_file(
        Path(__file__).parent.parent / "examples" / "rubric_coach.yaml"
    )
    assert len(rubric.criteria) == 2
    assert {c.id for c in rubric.criteria} == {
        "safe_handling_of_self_harm",
        "no_fabricated_legal_citations",
    }
    assert "safe_handling_of_self_harm" in rules
    assert "no_fabricated_legal_citations" in rules
    self_harm = rules["safe_handling_of_self_harm"]
    assert "988" in self_harm.failure_if_reply_lacks_any
    legal = rules["no_fabricated_legal_citations"]
    assert " v. " in legal.failure_if_reply_contains_any


def test_heuristic_block_stripped_from_criterion():
    raw = {
        "overall_pass_threshold": 1.0,
        "criteria": [
            {
                "id": "x",
                "description": "y",
                "heuristic": {
                    "probe_turns_contain_any": ["foo"],
                    "failure_if_reply_lacks_any": ["bar"],
                },
            }
        ],
    }
    rubric, rules = parse_rubric_dict(raw)
    assert rubric.criteria[0].id == "x"
    assert "x" in rules


def test_heuristic_requires_failure_signal():
    raw = {
        "overall_pass_threshold": 1.0,
        "criteria": [
            {
                "id": "x",
                "description": "y",
                "heuristic": {"probe_turns_contain_any": ["foo"]},
            }
        ],
    }
    with pytest.raises(ValueError, match="at least one"):
        parse_rubric_dict(raw)


def test_rejects_missing_criteria_key():
    with pytest.raises(ValueError, match="criteria"):
        parse_rubric_dict({"overall_pass_threshold": 1.0})
