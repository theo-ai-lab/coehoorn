<!-- Thanks for the patch. Coehoorn's whole pitch is honest, checkable verdicts, so
     the bar for changes is the same: small, tested, and reproducible. -->

**What this changes**

**Why**

**How it was verified**
- [ ] `uv run pytest -q` passes (full offline suite)
- [ ] `uv run ruff check .` is clean
- [ ] If output/report logic changed: `uv run python scripts/build_sample_report.py`
      leaves `git status` clean (the sample still regenerates **byte-for-byte**)
- [ ] If the judge or gold set changed: `uv run coehoorn meta-eval ...` numbers are
      included below, and any threshold move is justified
- [ ] If the gold set or judge changed: `uv run coehoorn mutation-score ...` still
      catches its load-bearing mutants (M1/M4); a new survivor is explained, not hidden

**Adversarial cases added** (if this touches the judge)
New gold cases — especially ones the heuristic gets wrong — go in
`tests/gold/judge_gold.jsonl`. List them here.

**Anything still unverified**
In the spirit of [`MISTAKES.md`](../MISTAKES.md): state plainly what you did *not* test.
