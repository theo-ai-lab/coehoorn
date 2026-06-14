# Examples

Self-contained inputs for the quickstart and for measuring the harness against a known target.

| file | what it is |
|---|---|
| `rubric_coach.yaml` | A two-criterion rubric (safe handling of self-harm language; no fabricated legal citations). Each criterion has a `heuristic:` block so the offline judge can decide it without an LLM call. |
| `rubric_tools.yaml` | The tool-policy rubric driving the tool-use siege: `forbidden_tools` (a destructive tool that must never be called — OWASP Agentic ASI02) and `tool_must_precede` (a privileged action requiring prior approval — ASI03). Powers `runs/sample-tools/`. |
| `expected_failures.yaml` | Per-persona ground-truth: which persona is expected to fail which criterion when this rubric is run against the local stub agent. Consumed by `coehoorn compare`. |

## Running the example

Start the stub agent in one terminal:

```
cd apps/stub-agent && uv run python app.py
```

In another terminal, from the repo root:

```
uv run coehoorn run \
  --rubric examples/rubric_coach.yaml \
  --agent http://127.0.0.1:8001/chat \
  --personas 6 --turns 4 --out runs

uv run coehoorn compare \
  --report runs/<run_id>.json \
  --expected examples/expected_failures.yaml
```

The `run` command writes `runs/<run_id>.json` (machine-readable) and `runs/<run_id>.html` (a self-contained report you can open with a browser).
