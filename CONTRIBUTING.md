# Contributing to Coehoorn

Coehoorn is a small, opinionated harness. The bar for a change is that it keeps
the core lean and the trust boundary honest.

## Setup

```bash
uv sync                       # core only — no extras
uv run pytest -q              # the full offline suite (no network, no API key)
uv run ruff check .
```

To work on the optional extras:

```bash
uv run --all-extras pytest tests/test_extras.py -q
```

## Principles

- **The schema is the contract.** Verdict invariants live in `schemas.py` as
  Pydantic validators, not in prompts. If you change what a valid verdict is,
  change it there and let every mode inherit it.
- **The judge holds itself to its own standard.** Any judgment a verdict makes
  must cite the turn that justifies it. A judgment that can't be made is an
  `ABSTAIN`, never a silent pass.
- **Dependency-budget rule.** Every new dependency must earn its place in an ADR
  (`docs/adr/`). The core has five runtime dependencies; keep it that way. The
  MCP and Inspect integrations are optional extras, lazily imported.
- **Determinism.** Heuristic mode is deterministic by construction. If a change
  introduces nondeterminism on that path, it's a bug.

## Tests

- Write the test first; the report's design constraints and the schema
  invariants are both pinned by tests, not by review alone.
- The LLM-mode meta-eval is **not** part of the default suite — it requires
  `ANTHROPIC_API_KEY` and `COEHOORN_RUN_LLM_META=1`, and it touches the network.
  The default `uv run pytest` is fully offline.

## Commit style

- Comments explain *why*, not *what*.
- No emoji in code, comments, or commit messages.
