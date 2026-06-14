---
name: Feature request
about: A failure mode you wish Coehoorn caught, or a capability it's missing
labels: enhancement
---

**The failure you want caught**
Describe the agent behavior Coehoorn should surface. A concrete adversarial case —
ideally one the current heuristic judge gets *wrong* — is the most useful thing you
can bring; it can go straight into the gold set.

**How you'd know it worked**
What would the verdict look like? Which turn should it cite?

**Scope check**
Coehoorn stays deliberately small (five runtime deps; six archetypes; cited-evidence
verdicts). See [`ROADMAP.md`](../../ROADMAP.md) — some asks are *intentionally* out of
scope (a learning adversary, telemetry, formal proofs). Say why this one earns its place.

**Alternatives you considered**
