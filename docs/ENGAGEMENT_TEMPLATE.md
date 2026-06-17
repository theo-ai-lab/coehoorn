# Engagement template — sieging a real external agent

A fill-in-the-blanks scaffold for a single Coehoorn engagement: *we pointed
Coehoorn at `<real agent X>`, found `N` cited breaches across these archetypes,
and here is how it is wired into their pipeline.* Copy this file to
`docs/engagements/<target>-<date>.md`, replace every `<...>`, and delete the
guidance blockquotes.

The value of this document is that **every claim is checkable**: each breach
points at a transcript turn, and the same SARIF/JUnit it cites is what the
target team already consumes in CI.

---

## 0. The un-fakeable part (read first)

> A live siege of a *real* agent cannot be faked. It requires two things this
> repo deliberately does not ship:
>
> 1. **A chosen endpoint** — a real agent's chat URL (`AGENT_ENDPOINT`), plus
>    any auth it needs (`AGENT_API_KEY` or `AGENT_AUTH_HEADER`).
> 2. **An `ANTHROPIC_API_KEY`** — only if you run LLM mode (richer personas and
>    a reasoning judge). Heuristic mode runs with no key but only decides
>    criteria that carry a `heuristic:` block.
>
> Everything else (the harness, the config shim, the CI wiring, this template)
> is in the repo and is mock-tested without a key. The numbers below are real
> only once a real endpoint and key are supplied. Do **not** paste fabricated
> results into this section — an empty table is more honest than an invented one.

---

## 1. Engagement summary

| field | value |
|---|---|
| Target agent | `<name + one-line description>` |
| Endpoint | `<https://.../chat>` (configured via `AGENT_ENDPOINT`, never committed) |
| Wire contract | `POST {conversation:[{role,content}...]} -> {reply: "..."}` |
| Rubric | `<examples/rubric_coach.yaml or a target-specific rubric>` |
| Mode | `<heuristic | llm>` |
| Personas × turns | `<6 × 4>` |
| Run date / commit | `<YYYY-MM-DD>` / `<coehoorn version + git sha>` |
| Run id | `<run_id from the report>` |

---

## 2. How it was wired (the config shim)

Coehoorn points at an arbitrary external agent with no code changes — the
endpoint and auth are resolved at runtime by `coehoorn/config.py`:

```bash
# Endpoint: flag wins, else env (CI injects from a secret/variable).
export AGENT_ENDPOINT="https://<target>/chat"

# Auth to the target (pick whichever the agent expects):
export AGENT_API_KEY="<token>"                 # -> Authorization: Bearer <token>
export AGENT_AUTH_HEADER="x-api-key: <token>"  # any raw header line

# Optional: LLM-mode personas + judge.
export ANTHROPIC_API_KEY="<key>"

uv run coehoorn run \
  --rubric "$RUBRIC" \
  --personas 6 --turns 4 \
  --out runs/<target> --emit sarif,junit --json
```

> `AGENT_API_KEY` authenticates Coehoorn **to the target**; it is distinct from
> `ANTHROPIC_API_KEY`, which powers Coehoorn's own LLM personas and judge.
>
> **If the target speaks a different wire shape** than
> `{conversation} -> {reply}` (e.g. OpenAI/Anthropic Messages, or a bespoke
> envelope), write a thin adapter: subclass or wrap `HttpAgentAdapter`, or pass
> any `async (conversation) -> str` callable (see `CallableAdapter` in
> `coehoorn/agent_adapter.py`). The rest of the harness is unchanged.

---

## 3. Results — cited breaches

> Pull these straight from `runs/<target>/<run_id>.json` (or the SARIF). Do not
> hand-edit the counts. The HTML report (`<run_id>.html`) is the artifact to
> attach for the client.

Headline: **`<N>` cited breaches** out of `<personas>` approaches —
`<pass_rate>`% held, `<abstention_rate>`% abstained.

### Breaches by archetype

> The six archetypes are: `contradictor`, `ambiguous`, `emotional`,
> `off_topic`, `injector`, `edge_case`.

| archetype | breaches | criteria broken |
|---|---|---|
| `<emotional>` | `<n>` | `<criterion_id, ...>` |
| `<injector>` | `<n>` | `<...>` |
| `<...>` | `<n>` | `<...>` |

### Every breach, cited to the turn

> One row per SARIF result. `turn` is the cited transcript index that proves
> the breach — this is the column that makes the finding non-hand-wavy.

| archetype / persona | criterion | turn | what happened |
|---|---|---|---|
| `<emotional / p02>` | `<safe_handling_of_self_harm>` | `<3>` | `<rationale from the verdict>` |
| `<injector / p04>` | `<...>` | `<...>` | `<...>` |

### Where the wall held / where the judge abstained

> Hold the honest line: list approaches that did **not** breach, and any cells
> the judge abstained on (low confidence / out of heuristic scope). Abstentions
> are not passes.

---

## 4. The integration (continuous siege)

The engagement does not end with one run. `.github/workflows/external-siege.yml`
turns it into a standing gate:

- Set `AGENT_ENDPOINT` (secret or repo variable) and any auth secrets in the
  target's repo settings.
- On every PR and nightly, the workflow sieges the configured agent, uploads
  the cited breaches to the **Security tab** (SARIF), publishes a **JUnit**
  test report, and posts a **PR comment** listing each breach with its cited
  turn.
- With no `AGENT_ENDPOINT` configured (e.g. a fork PR), the workflow **no-ops
  gracefully** — the check stays green, nothing leaks.
- To make a breach a hard gate, add `--fail-on-breach` to the run step.

> The local-stub workflow (`.github/workflows/siege.yml`) stays as the offline,
> key-free demo; `external-siege.yml` is the real-target counterpart.

---

## 5. Remediation & next steps

> For each breach class, the concrete fix and how to confirm it: re-run the same
> rubric and watch the cited breach disappear (or the SARIF result count drop).

| breach class | recommended fix | how we'll verify |
|---|---|---|
| `<self-harm referral missing>` | `<safety-routing on crisis intents>` | `<re-siege; criterion holds>` |
| `<...>` | `<...>` | `<...>` |

---

## 6. Reproducing this engagement

```bash
# 1. Configure the (un-fakeable) target + keys — see §2.
# 2. Re-run the exact command in §2 with the same rubric/personas/turns.
# 3. Diff the breach set against this report's run_id.
```

> Attach: `runs/<target>/<run_id>.html` (self-contained report),
> `<run_id>.sarif.json`, and `<run_id>.junit.xml`.
