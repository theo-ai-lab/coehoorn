"""Exports the tool-use siege as Plimsoll traces under runs/sample-tools/traces/.

The traces are a pure function of the committed run record (see
coehoorn/trace_export.py), so this is byte-reproducible: re-running it must
never dirty `git diff` — tests/test_trace_export.py gates exactly that.

Re-run with: `uv run python scripts/export_plimsoll_traces.py`.

Gate the result (requires plimsoll; the demo agent is deliberately flawed, so
the expected verdict is FAIL with one `forbidden_tool` and one `tool_order`
finding per case — the same two breaches Coehoorn's judge cites):

    plimsoll run --input runs/sample-tools/traces \\
        --policy examples/plimsoll_policy_tools.json \\
        --out runs/trace-gate --sarif
"""
from __future__ import annotations

from pathlib import Path

from coehoorn.aggregator import load_report_json
from coehoorn.trace_export import write_trace_files

REPO_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    report = load_report_json(REPO_ROOT / "runs" / "sample-tools" / "report.json")
    paths = write_trace_files(report, REPO_ROOT / "runs" / "sample-tools" / "traces")
    for path in paths:
        print(f"wrote: {path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
