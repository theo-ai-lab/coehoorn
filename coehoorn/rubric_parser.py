"""Rubric YAML parser.

Reads a rubric YAML file and returns (Rubric, heuristic_rules). The
Rubric is the public contract the judge scores against; heuristic_rules
is a side-table consumed only by the offline heuristic judge (LLM judge
ignores it). Keeping heuristic rules out of the Criterion schema
preserves the wire contract's purity — a Criterion is what the judge
must decide, not how a fixture mode short-circuits it.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from .schemas import Criterion, Rubric


class HeuristicCriterionRule(BaseModel):
    """Companion rule for one Criterion used by the offline heuristic judge.

    `probe_turns_contain_any` — at least one user turn must contain one of these
    substrings (lowercased compare) for the rule to be in scope. If the rule is
    not in scope for a transcript, the criterion is recorded as PASS with the
    rationale that the persona didn't exercise this failure mode here.

    `failure_if_reply_lacks_any` — once in scope, the immediately-following
    assistant reply fails the criterion if it contains NONE of these
    substrings (e.g. safety language).

    `failure_if_reply_contains_any` — alternative failure signal: the assistant
    reply fails the criterion if it contains ANY of these substrings (e.g. a
    fabricated-citation pattern).

    A rule must set at least one of the two failure signals. They are OR-ed.
    """

    model_config = ConfigDict(extra="forbid")

    probe_turns_contain_any: list[str] = Field(default_factory=list)
    failure_if_reply_lacks_any: list[str] = Field(default_factory=list)
    failure_if_reply_contains_any: list[str] = Field(default_factory=list)
    # Tool-policy signals (OWASP Agentic ASI02 misuse / ASI03 privilege abuse):
    #   forbidden_tools     — the agent calling any of these is a breach.
    #   tool_must_precede   — (before, after) pairs; calling `after` without an
    #                         earlier `before` (e.g. a privileged action with no
    #                         prior approval) is a breach. Order, not presence:
    #                         never calling `after` is fine.
    forbidden_tools: list[str] = Field(default_factory=list)
    tool_must_precede: list[tuple[str, str]] = Field(default_factory=list)
    failure_message: str = "Heuristic rule matched."


def parse_rubric_file(
    path: str | Path,
) -> tuple[Rubric, dict[str, HeuristicCriterionRule]]:
    """Parse a rubric YAML at `path`.

    Returns the Rubric (schema-validated) and a {criterion_id: HeuristicCriterionRule}
    mapping for criteria that supplied a `heuristic:` block. Criteria without one
    are excluded from the mapping; the heuristic judge ABSTAINS on them (it has no
    offline basis to decide them).
    """
    try:
        raw = yaml.safe_load(Path(path).read_text())
    except yaml.YAMLError as exc:
        # Surface malformed YAML as a clean ValueError so every CLI handler's
        # load guard reports it uniformly, instead of leaking a yaml traceback.
        raise ValueError(f"Rubric YAML {str(path)!r} is not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"Rubric YAML must be a mapping; got {type(raw).__name__}")
    return parse_rubric_dict(raw)


def parse_rubric_dict(
    raw: dict[str, Any],
) -> tuple[Rubric, dict[str, HeuristicCriterionRule]]:
    if "criteria" not in raw:
        raise ValueError("Rubric must include a 'criteria' list.")

    heuristic_rules: dict[str, HeuristicCriterionRule] = {}
    criteria_clean: list[dict[str, Any]] = []
    for c in raw["criteria"]:
        if not isinstance(c, dict):
            raise ValueError(f"Each criterion must be a mapping; got {type(c).__name__}")
        c_copy = dict(c)
        heuristic_block = c_copy.pop("heuristic", None)
        criteria_clean.append(c_copy)
        if heuristic_block is not None:
            cid = c_copy.get("id")
            if not isinstance(cid, str):
                raise ValueError("Criterion with heuristic block must have a string id.")
            rule = HeuristicCriterionRule.model_validate(heuristic_block)
            if not (
                rule.failure_if_reply_lacks_any
                or rule.failure_if_reply_contains_any
                or rule.forbidden_tools
                or rule.tool_must_precede
            ):
                raise ValueError(
                    f"Heuristic rule for criterion {cid!r} must set at least one failure "
                    "signal (reply content or tool policy)."
                )
            heuristic_rules[cid] = rule

    rubric_data = {
        "criteria": [Criterion.model_validate(c) for c in criteria_clean],
        "overall_pass_threshold": raw.get("overall_pass_threshold", 1.0),
    }
    rubric = Rubric.model_validate(rubric_data)
    return rubric, heuristic_rules
