# ROI model — framing the value of a siege

*A cost-benefit **model**, not a result. It gives `[CLIENT]` a structured way to
weigh the cost of an engagement against the cost of the failures it surfaces —
using **only numbers `[CLIENT]` supplies**. There is exactly one worked example
below, and it is **labelled illustrative and is not a real client result**.*

> **Anti-fabrication rule for this document (and any deliverable built from it):**
> every dollar figure, incident rate, or hours-saved value is one of:
> **CLIENT-SUPPLIED** (you give us the number), or **illustrative (not a real
> result)** (a placeholder to show the arithmetic). We never assert a savings we
> measured. Coehoorn's job is to surface *cited breaches*; what a breach is worth
> is a business judgment only `[CLIENT]` can make.

Method context: [METHODOLOGY.md](./METHODOLOGY.md). Pricing structures (also
illustrative): [SOW §10](./SOW_TEMPLATE.md).

---

## 1. The model in one picture

```
            value found by the siege
ROI ratio = ─────────────────────────
            cost of the engagement

where value = (avoided incident cost) + (engineering time saved)
                                       + (avoided tail / breach event)
```

Every term on the right is built from `[CLIENT]`-supplied inputs. The siege does
not *create* the value — it **finds, with cited evidence, the breaches** whose
remediation realizes it. Whether a found breach would have caused an incident is
a judgment `[CLIENT]` makes per breach; the model just gives the arithmetic.

---

## 2. Inputs — all CLIENT-SUPPLIED

> Fill every cell. If you don't have a number, mark it `TBD` rather than
> guessing — a model built on an invented input is worse than no model.

| Symbol | Input | Unit | Source | Value |
|---|---|---|---|---|
| `I` | Agent-caused incidents per month *(today)* | incidents / mo | CLIENT-SUPPLIED | `[ ]` |
| `C_i` | Fully-loaded cost per incident | `[$]` / incident | CLIENT-SUPPLIED | `[ ]` |
| `p` | Share of those incidents that fall **in Coehoorn's scope** (multi-turn behavioral / tool-policy — see coverage-map) | 0–1 | CLIENT-SUPPLIED (we advise) | `[ ]` |
| `r` | Share of in-scope incidents a pre-deploy siege + fix would have prevented | 0–1 | CLIENT-SUPPLIED (we advise) | `[ ]` |
| `H` | Eng-hours / month spent triaging or reproducing these failures by hand | hours / mo | CLIENT-SUPPLIED | `[ ]` |
| `w` | Fully-loaded eng cost per hour | `[$]` / hour | CLIENT-SUPPLIED | `[ ]` |
| `f` | Fraction of `H` displaced by a reproducible, cited, CI-wired siege | 0–1 | CLIENT-SUPPLIED (we advise) | `[ ]` |
| `B` | Value of avoiding **one** tail/breach event (regulatory, trust, outage) | `[$]` / event | CLIENT-SUPPLIED | `[ ]` |
| `q` | Probability/yr the siege prevents one such event | 0–1 / yr | CLIENT-SUPPLIED (we advise) | `[ ]` |
| `E` | Engagement cost (provider fee + API token cost, see SOW §10) | `[$]` | from SOW | `[ ]` |
| `T` | Horizon for the comparison | months | CLIENT-SUPPLIED | `[ ]` |

> `p`, `r`, `f`, `q` are the honest, judgment-laden inputs. We will *advise* on
> ranges and sensitivity, but the number is `[CLIENT]`'s — and we recommend
> running the model across a **low/expected/high** band rather than a single
> point (see §5).

---

## 3. The formula

Over a horizon of `T` months:

```
Avoided incident cost   A = I × C_i × p × r × T
Engineering time saved  S = H × w × f × T
Avoided tail event      G = B × q × (T / 12)

Total modeled value     V = A + S + G
Net                     N = V − E
ROI ratio               R = V / E         (break-even at R = 1)
Payback (months)        P = E / ((V) / T)  = E / (monthly modeled value)
```

That is the whole model. No hidden terms, no assumed multipliers — what you put
in is what comes out.

---

## 4. Worked example — ILLUSTRATIVE (not a real client result)

> **READ THIS LINE:** every number below is **made up to demonstrate the
> arithmetic**. It is **not** a measured outcome, **not** a past client, and
> **not** a claim about what `[CLIENT]` will save. Substitute your own §2 inputs.

Illustrative inputs (fictional):

| Symbol | Illustrative value |
|---|---|
| `I` | 8 incidents / mo *(illustrative)* |
| `C_i` | $4,000 / incident *(illustrative)* |
| `p` | 0.40 *(illustrative)* |
| `r` | 0.50 *(illustrative)* |
| `H` | 20 hours / mo *(illustrative)* |
| `w` | $120 / hour *(illustrative)* |
| `f` | 0.50 *(illustrative)* |
| `B` | $250,000 / event *(illustrative)* |
| `q` | 0.10 / yr *(illustrative)* |
| `E` | $60,000 *(illustrative)* |
| `T` | 12 months *(illustrative)* |

Illustrative arithmetic (rounded):

```
A = 8 × 4000 × 0.40 × 0.50 × 12   = $76,800   (illustrative)
S = 20 × 120 × 0.50 × 12          = $14,400   (illustrative)
G = 250000 × 0.10 × (12/12)       = $25,000   (illustrative)
V = A + S + G                     = $116,200  (illustrative)
N = V − E = 116,200 − 60,000      = $56,200   (illustrative)
R = V / E = 116,200 / 60,000      ≈ 1.9×      (illustrative)
P = 60,000 / (116,200 / 12)       ≈ 6.2 months (illustrative)
```

**What this example does and does not say.** It shows the model produces a
defensible ratio *if* the inputs hold. It says **nothing** about any real agent
or any real client — change `p`, `r`, `q` and the ratio can fall below 1.0,
which is exactly why these are inputs, not assumptions.

---

## 5. Honest framing (how to present this without overclaiming)

- **Run a band, not a point.** Present `R` and payback `P` at low / expected /
  high values of the judgment inputs (`p`, `r`, `f`, `q`). A model that only
  survives at its optimistic corner is not a case for the work.
- **The hardest input is `r`** (incidents a pre-deploy siege would have
  prevented). Coehoorn covers a narrow slice (see
  [`../coverage-map.md`](../coverage-map.md)); `p` should reflect that scope
  honestly, and out-of-scope incidents should be excluded from `A`, not
  hand-waved in.
- **Engineering time saved (`S`) is the most defensible term** — it rests on a
  reproducible, cited, CI-wired siege displacing manual repro work, which is a
  capability the tool actually has (deterministic heuristic mode, SARIF/JUnit,
  the standing `external-siege.yml`).
- **The tail term (`G`) is the least defensible** — a single low-probability,
  high-cost event. Present it separately and let `[CLIENT]` decide whether to
  count it at all.
- **Never report `V`, `N`, `R`, or `P` as an achieved result.** They are modeled
  values from `[CLIENT]`-supplied inputs. In any engagement deliverable they
  carry the label *"modeled from client-supplied inputs, not a measured
  outcome."*

---

## 6. What we will *not* put in this model

- A "typical customer saves `$X`" benchmark — we have no such data and will not
  invent one.
- A breach-count target dressed up as a dollar figure — acceptance is about cited
  evidence, not a count (see [SOW §8](./SOW_TEMPLATE.md)).
- Any reliability/accuracy percentage attributed to the agent or the judge that
  isn't traceable to a `meta-eval` / `mutation-score` run on real inputs. Until a
  live run exists, such numbers stay `pending`.
