# What broke, and what it taught me

Coehoorn is a tool about honest reporting, so this file holds itself to the same
standard: the real mistakes made building it, the false positives the tool itself
produces, and what's still unverified. None of this is hypothetical — each item
shipped, broke, and was caught.

---

## 1. "Deterministic" wasn't — until a test ran it twice

The README claimed the sample report was reproducible. It wasn't: `run_id` used a
random UUID and the timestamps used `now()`, so every regeneration produced a
different file. The *verdicts* were deterministic; the *artifact* was not, and the
one command the README hands a skeptic (`build_sample_report.py`) left `git status`
dirty.

**Fix:** separate substance (seed-deterministic) from provenance (timestamps,
run id); pin provenance for the canonical artifact; add a test that runs the whole
pipeline twice and asserts identical bytes.
**Lesson:** a determinism claim needs a test that *diffs bytes across two runs* —
"deterministic logic" and "deterministic output" are not the same thing.

## 2. A silent coerce-to-pass corrupted the metric it sat under

The heuristic judge had a branch that, when it couldn't cite a turn, flipped the
outcome to `pass`. That meant a "should have failed but couldn't prove it" quietly
became a pass — *inside the false-negative count of the very meta-eval that pins the
CI thresholds.* The headline credibility number was computed on top of a known
semantic hole.

**Fix:** introduce an explicit three-valued state (`pass` / `fail` / **abstain**) so
"couldn't decide" is recorded, not laundered into a pass — and resolved it *before*
freezing any gold labels.
**Lesson:** fix the substrate before you measure on it. A hole under your headline
metric invalidates the metric, not just the edge case.

## 3. The hero report showed an all-1.00 victory lap

The committed report's calibration panel printed precision/recall of **1.00** —
because it scored the judge against its *own* expected-failures fixture, which was
hand-labeled to match. The honest number (the judge's ~0.66 balanced accuracy on an
adversarial gold set) lived only in a separate command. A sharp reviewer reads
all-1.00 as a brag, and it quietly contradicted the project's own thesis.

**Fix:** the report now shows the **gold** calibration — ~0.66 with Wilson intervals
and dumb baselines — not the self-fulfilling 1.0.
**Lesson:** publish your tool's failure rate. A sub-1.0 score beside baselines reads
as someone who has actually run evals; a perfect score reads as decoration.

## 4. The tool's own false positives (documented, not hidden)

The cheap keyword judge has predictable blind spots, and the gold set is *built* to
expose them. It:
- flags a correctly-cited **real** case (`Roe v. Wade`) as fabricated — a false
  positive it can't avoid, because it pattern-matches `" v. "`;
- **misses** a fabricated citation phrased as `Matter of …` to dodge that pattern;
- **passes** a dismissive, unsafe self-harm reply because it name-drops "doctor".

**Lesson:** a heuristic has knowable failure modes — enumerate and measure them
rather than pretending they don't exist. That gap is the honest argument for the
stronger LLM judge, not something to bury.

## 5. Structural tests passed; the render was still wrong

My geometry validator checked that every SVG coordinate sat inside the viewBox — and
it did. But it checked *anchor points*, not rendered *text extent*, so a label
overflowed the right edge and clipped. Only a human looking at the actual render
caught it; the test was green.

**Fix:** widen the viewBox and add a regression test that estimates each label's
*extent*, not just its origin.
**Lesson:** structural tests are not visual verification. Some bug classes need eyes
(or a test written to model what the eye sees).

## 6. The network boundary had zero tests and churned a connection per turn

The HTTP adapter — the one piece that touches the network — opened and closed a fresh
client on *every turn* of a conversation, and had no direct test at all.

**Fix:** reuse one owned client across the conversation (async context manager) and
test the boundary (reuse, close-on-exit, injected-client handling, the reply
contract).
**Lesson:** test the thing at the edge. "It worked in the demo" hides per-call cost
and leaves the riskiest seam unguarded.

## 7. A check that only looked at tracked files missed an untracked one

A test fixture referenced an environment-specific identifier it should not have.
A search with `git grep` — which only sees tracked files — missed it, because the
offending file was still untracked.

**Fix:** check the entire working tree (tracked *and* untracked), not just what
`git grep` sees.
**Lesson:** a check that only looks where it's convenient gives false assurance.
Scan the whole surface.

---

## Still unverified (stated plainly)

The **LLM mode** (Opus-voiced personas + a Sonnet judge) runs the full path
end-to-end with a key, but it is non-deterministic, so no LLM sample is committed
(regenerate one with `scripts/build_sample_report_llm.py`).

What is still **unverified is its measured accuracy.** The LLM judge has not been
scored against the labeled gold set, so — unlike the heuristic judge's honest
~0.66 balanced accuracy — there is no precision/recall number for it yet. The next
honest step is a bounded calibration run scoring the LLM judge against the gold set
— does it actually beat 0.66? — with the numbers published here. Until then, I make
no performance claim about it I haven't produced.
