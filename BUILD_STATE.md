# Coehoorn — Build State (snapshot: 2026-06-13)

A plain-language status of where the build stands right now. If you've never heard
of this project, start at §0; if you just want "is it done and what's left," read §1
and §7.

---

## 0. What this is, in 30 seconds (zero context needed)

Coehoorn is a tool that **stress-tests a chatbot to find where it breaks — and proves
each flaw.** It sends six kinds of difficult users at a chat agent (a contradictor, a
vague rambler, someone in distress, an off-topic prober, a prompt-injector, an
edge-case tester), holds real multi-turn conversations, and grades each one against a
plain-English checklist you write. When it says "your agent failed here," it points
at the exact message in the transcript that proves it — and it's engineered so a flaw
with no proof attached *cannot even be recorded.* It runs entirely on your machine,
offline, and outputs one self-contained HTML report drawn like an old map of a fort
under siege, where each broken wall is a place the agent failed.

*(Full detail in [`OVERVIEW.md`](./OVERVIEW.md). This file is just the build status.)*

---

## 1. Status at a glance

| | |
|---|---|
| **Version** | v0.2 — feature-complete |
| **Tests** | **233 total — 231 pass fully offline, 2 gated behind optional add-ons** |
| **Lint** | clean (`ruff`) |
| **Determinism** | the sample reports regenerate **byte-for-byte identical** |
| **Code** | 16 modules, ~5,000 lines; **5 runtime dependencies** (citation-integrity suite added zero) |
| **Published?** | **No.** Deliberately local-only for now. |
| **The one real gap** | the LLM judge's **accuracy is unmeasured** — the live path now runs end-to-end with a key but it has not been scored against the gold set |

**Bottom line:** functionally complete and green; the LLM path now runs live
end-to-end but its accuracy is not yet measured; nothing is published.

---

## 2. What's actually been built

**The core engine (all working, all tested):**
- A typed pipeline: rubric → adversarial personas → multi-turn conversations → judge →
  validated report.
- A **trust boundary** enforced by the data schema: judgments are three-valued
  (pass / fail / **abstain**), and illegal combinations (a failure citing no
  evidence, a "pass" citing a breach, a citation to a turn that doesn't exist) raise an
  error at construction — they can't be recorded.
- **Two modes:** a deterministic, offline *heuristic* mode (no API key, fully
  exercised) and a *smarter LLM* mode (Anthropic models; wired and schema-guarded).
- An **"audit the auditor" meta-eval:** the tool grades its *own* judge against a
  frozen, hand-labeled gold set — reporting precision / recall / balanced accuracy with
  confidence intervals, against dumb baselines. The gold set is deliberately stocked
  with traps, so the cheap judge honestly scores ~0.66, not a fake 1.0. (Measuring its
  own failure rate is the point.)
- A **citation-integrity suite that audits the audit** (added this pass, zero new
  runtime deps):
  - `coehoorn mutation-score` plants six broken "mutant" judges and proves the gold set
    catches each. The two discriminating ones corrupt *only* the cited turn — bugs a
    status confusion matrix is blind to — caught via a new `gold_cited_turn`
    ground-truth anchor. The honest score is **4/6**, and the two survivors *name the
    gold cell that would catch them*. It's a deterministic count, so it ships without a
    confidence interval (a CI on a fixed count would be false precision).
  - `coehoorn metamorphic` (CITE-MR) rewrites a transcript in meaning-preserving ways
    (rename / renumber / insert / paraphrase) and checks the verdict **and the cited
    turn** stay put. The deterministic judge is the by-construction control; the
    stochastic LLM judge is the real target, gated by Fisher's exact + Holm rather than
    a normal-approximation z-test.

**The output (the "Siege Survey"):**
- One self-contained HTML file — no JavaScript, no external assets, opens offline,
  prints cleanly. An inline-SVG fort with one wall-face per adversary type; breaches
  drawn as gaps in the wall at the cited turn; a loud result tally; a calibration
  panel; and the full cited transcripts.

**The machine-facing surfaces (for automation):**
- A command-line interface (`run`, `compare`, `meta-eval`, `mutation-score`,
  `metamorphic`) with a stable JSON output mode, opt-in gate exit codes
  (`--fail-on-breach`, `--min-score`, `--fail-on-instability`), and a machine-readable
  `report.json`.

**Two optional add-ons (lazy, don't touch the core):**
- An MCP server so another AI agent can run a siege as a tool.
- An exporter to Inspect AI (the UK AISI eval framework) so a run opens in a standard
  eval viewer.

**Docs:** README, a granular architecture doc, a decision register (with the
deliberately-*rejected* options), an eval-methodology writeup, a standards
coverage-map (with gaps openly listed), and a one-page brief.

---

## 3. How it got here (the build journey)

1. **v0.1 → v0.2 rigor pass.** Replaced a binary pass/fail with the three-valued
   trust model, built the self-auditing meta-eval from scratch, made the sample
   byte-reproducible, and added the CLI automation surfaces and the two optional
   add-ons.
2. **The report redesign.** Rebuilt the HTML report as the bespoke "Siege Survey"
   (and removed a dependency in the process).
3. **Report revision after review.** The report was revised to show the judge's
   *honest* ~0.66 accuracy with baselines instead of a misleading perfect score.
4. **Code-review hardening.** Ten review issues (one a genuine crash) were fixed,
   each with a new regression test.
5. **Boundary hardening.** Fixed and tested the network adapter (it now reuses one
   connection per conversation instead of opening a new one every turn).

Each step ended green: tests passing, lint clean, sample reproducible.

---

## 4. Verified vs. not (the honest line)

- **Fully verified:** the entire *heuristic* path — personas, conversations, the judge,
  the report, the meta-eval, the CLI, the schema invariants, the adapter — is exercised
  by the offline test suite and reproduces byte-for-byte.
- **Run live, but accuracy unmeasured:** the *LLM* mode (Opus personas + Sonnet judge)
  has been run end-to-end against a real API key (non-deterministic, so no sample is
  committed). What is *not* yet done is **calibration**: the LLM judge has not been
  scored against the gold set, so there is no precision/recall number for it (unlike
  the heuristic's honest ~0.66). This is the single honest hole that remains.

---

## 5. Quality evidence (so the claims are checkable)

- 231 offline tests (233 total, 2 gated); the schema invariants, the report's design
  constraints, the meta-eval numbers, the mutation score's load-bearing/confirmatory
  split, the metamorphic Fisher+Holm gate, byte-reproducibility, and the network
  boundary are each pinned by tests.
- The 10-second "you can't record a dishonest verdict" claim is itself a test (and a
  copy-paste snippet in the README).
- Lint clean; 5 runtime dependencies, each (and each rejected alternative) justified in
  the decision register.

---

## 6. What's next

**Recently shipped (✅ done):**
- **Live LLM run (end-to-end)** — the Opus-personas + Sonnet-judge path was run against
  a real API key (non-deterministic, not committed as a sample). The full LLM path is
  *exercised*, not just wired — though its accuracy is still unmeasured (see §4).
- **Citation-integrity suite** — `mutation-score` (mutation-test the gold set; honest
  4/6 with named survivors) and `metamorphic` / CITE-MR (verdict + citation stability
  under semantics-preserving transforms, gated with Fisher's exact + Holm). Measures the
  one property the schema can't guarantee — citation *faithfulness* — instead of
  asserting it. Zero new runtime deps; both are stdlib-only and offline by default.
- **Tool-use attack surface** — the tool now tests *agents*, not just chat. Transcripts
  capture tool calls; rubrics can forbid tools and require approval before privileged
  actions, mapped to the **OWASP Agentic 2026** risks ASI02 (tool misuse) and ASI03
  (privilege/approval bypass). Ships a committed tool-siege demo.
- **SARIF + JUnit output** — `--emit sarif,junit` plus a GitHub Action that uploads
  findings to the Security tab. Drop-in CI/security integration.
- **Launch-readiness bundle** — a candid `MISTAKES.md` (what broke + still-unverified),
  a `ROADMAP.md` (with a deliberately-out-of-scope section), a reproducible demo script
  (`docs/demo.tape`), issue/PR templates, and README badges + a "See it run" section.
  All local; nothing published.

**Still ahead (bounded):**
- **Calibrate the LLM judge** *(hours; needs an API key).* Score the LLM judge against
  the labeled gold set and publish its precision/recall vs the heuristic's ~0.66 — the
  live path now runs end-to-end, but its accuracy is still unmeasured (§4).
- **Publish.** The public release is a deliberate manual step and is not yet done.

---

## 7. Known gaps & honest limitations

- **The LLM judge's accuracy is unmeasured** (§4) — the live path now runs end-to-end
  with a key, but the LLM judge has not been scored against the gold
  set, so no precision/recall claim is made for it.
- **Tool coverage is a thin, real slice** — it now catches forbidden-tool calls and
  approval/privilege bypass (OWASP Agentic ASI02/ASI03), but not memory/context
  poisoning, inter-agent communication, or multi-agent cascades.
- **Six fixed adversary types, not a learning attacker** — it's a small, opinionated
  harness, not an automated adaptive red team.
- **Schema integrity ≠ judge correctness** — it guarantees every flaw is tied to real,
  checkable evidence; it does *not* guarantee the judge's reasoning about that evidence
  is right. The citation-integrity suite now *measures* that gap (mutation score +
  metamorphic stability) rather than closing it — measurement, not a guarantee.
- **No users yet** — it's a finished, tested, documented tool that, as of today, no one
  but its author has run. That's a deliberate state, not an oversight.

---

## 8. See it for yourself

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync && uv run pytest -q                       # install + run the full offline suite
uv run python scripts/build_sample_report.py      # regenerate the deterministic sample
open runs/sample/report.html                      # the Siege Survey (macOS; else xdg-open)
uv run coehoorn meta-eval \                          # watch it grade its own judge
  --gold tests/gold/judge_gold.jsonl --rubric examples/rubric_coach.yaml
uv run coehoorn mutation-score \                     # then watch it audit that grade (honest 4/6)
  --gold tests/gold/judge_gold.jsonl --rubric examples/rubric_coach.yaml
uv run coehoorn metamorphic \                        # citation stability under meaning-preserving edits
  --rubric examples/rubric_tools.yaml --from-report runs/sample-tools/report.json
```
