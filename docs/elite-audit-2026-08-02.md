# Ship-gate ledger — coehoorn, 2026-08-02

Branch: `hardening/error-outcomes-and-redaction`. Two verdicts, reported
separately and never merged.

## What this gate caught

The loopback engagement report concluded "Zero behavioural findings. The money
gate held against every archetype." The same page states that no transcript was
obtained, that every approach was refused before a reply existed, and that the
harness refused to write a findings report and exited 2.

Six approaches were turned away at the HTTP layer with 401 and 405. The
archetypes were never exercised as archetypes — a persuasion strategy that never
reaches a model has not been tested against it. "Zero behavioural findings"
meant zero behaviour was observed, not that observed behaviour was clean.
Reading an empty result set as a passing one is the exact error this harness
exists to prevent. The claim is withdrawn in place and the README no longer
repeats it.

Also reconciled: `CriterionStatus`'s docstring forbade collapsing abstention
into pass, while the heuristic judge does exactly that for one case — a
criterion whose probe never matched any user turn. That is a deliberate
modelling choice and the frozen gold set encodes the same reading, so the
docstring now records the exception and its cost (pass rates include unexercised
criteria) instead of stating an absolute the code breaks. Making it abstain was
attempted and reverted: it moves the gold labels, the confusion matrix, the
distillation coverage figure and the published calibration numbers together, and
updating those expectations to match new output would be fitting the tests to
the code. **This is the top follow-up.**

## Scores

| # | Principle | Score | Evidence |
|---|---|---|---|
| P12 | Testing | **4** | 609 passed / 4 skipped from a cold clone; mypy strict clean on 33 modules; ruff clean. Mutation suite (`test_judge_mutants`) proves which seam kills each seeded mutant. |
| P13 | CI/CD | **3** | Lint, types, tests, and an external-siege workflow. **Evidence is the PR run.** Known gap recorded: SARIF/JUnit emitters iterate completed verdicts only, so a partial run can render as a clean sweep. |
| P14 | Observability | **3** | Cited-artifact reports; every failure carries a turn index the schema requires to exist. |
| P15 | Security fundamentals | **4** | Scope pinning against DNS rebind — the checked addresses are dialled, not re-resolved — with the proxy-environment bypass closed and tested. Redaction across emitters. Engagements are `authorized: false` by default and unrunnable without written authorization. |
| P19 | Infrastructure | **3** | Zero-network offline judge path; loopback stub target; uv-managed. |
| P24 | Measurable success criteria | **3** | Selective-risk certification with Wilson/Hoeffding intervals. Scored 3 not 4: the calibration cases are deterministic and derived from the development gold set, so the distribution-free bound's independence assumption is asserted rather than established. |
| P32 | Graders | **4** | Tri-state judge (pass/fail/abstain) with a meta-eval over a frozen gold set, plus a mutation harness that checks the grader catches seeded grader defects. |
| P36 | Onboarding / accurate mental models | **3** | External adversarial review by an independent frontier model from a different vendor. Its blocker — that a cited turn is only a referentially valid pointer, not proof — is a fair narrowing of the top-fold wording and is recorded as open. The false "held against every archetype" claim it surfaced is fixed. |

## Verdict 1 — Build Quality

**Strong on the security spine, honest about the judge.** The scope-pinning work
is the best part: the address that passed the check is the address dialled, so a
DNS rebind between check and connect cannot move the target, and the
proxy-environment escape from that guarantee is closed and tested.

The judge is weaker than the spine, and the repo mostly says so. What it did not
say, and now does, is that an unexercised criterion counts as a pass.

## Verdict 2 — External Adoption / Production Validation

**Unproven. No external users, and no completed external siege.** The one run
against a service this repo did not write produced no transcript and no verdict.
The first genuinely third-party target is defined, scoped, and deliberately
unauthorized pending written permission. Nothing here has been run against a
stranger's agent.
