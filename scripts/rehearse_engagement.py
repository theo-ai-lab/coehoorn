"""One command: conduct an engagement against a real HTTP target and emit a report.

    uv run python scripts/rehearse_engagement.py

It starts the rehearsal target (`apps/approval-stub`, a stdlib HTTP server on
loopback), points the engagement runner at it over a real socket, and prints
the three artifacts it wrote.

What this proves, precisely: the engagement spine works end to end — the
authorization gate, the scope check, the HTTP adapter, the per-archetype
probes the engagement declares, the offline judge, the redaction boundary, and
a findings artifact whose every citation resolves.

What it does NOT prove: anything about a third party. The target is owned by
this repository and its weakness is planted and documented (see the
`apps/approval-stub/approval_surface.py` docstring). A number produced here is
not evidence about someone else's agent. The first *real* target is defined,
scoped and deliberately unauthorized in
`docs/engagements/farthing-approval-surface.yaml`.

Pass `--out DIR` to write elsewhere (default: `runs/rehearsal/`).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import threading
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "apps" / "approval-stub"))

from approval_surface import make_server  # noqa: E402

from coehoorn.engagement import load_engagement, run_engagement  # noqa: E402

ENGAGEMENT = REPO_ROOT / "docs" / "engagements" / "local-approval-rehearsal.yaml"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(REPO_ROOT / "runs" / "rehearsal"))
    args = parser.parse_args(argv)

    engagement = load_engagement(ENGAGEMENT)
    server = make_server()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[0], server.server_address[1]
    target = f"http://{host}:{port}/decide"
    print(f"rehearsal target listening on {target}")
    print(f"engagement: {engagement.id} (authorized: {engagement.authorized})")
    try:
        result = asyncio.run(run_engagement(engagement, target=target, out_dir=args.out))
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()

    print(
        f"\n{len(result.findings)} finding(s) across {result.transcripts} of "
        f"{result.approaches_attempted} approaches"
        f"{'  [PARTIAL]' if result.partial else ''}"
    )
    for f in result.findings:
        mark = "critical" if f.critical else "finding"
        print(
            f"  [{mark}] {f.persona_id} ({f.archetype.value}) "
            f"{f.criterion_id} @ turn {f.cited_turn_index}"
        )
    print(f"\nrecord: {result.record_json}")
    print(f"json:   {result.report_json}")
    print(f"html:   {result.report_html}")
    print(
        "\nReminder: the target above is this repository's own deliberately "
        "weakened stub. This is a rehearsal, not an external siege."
    )
    # Echo the record so a reader sees the engagement-shaped artifact without
    # opening a file.
    print("\n--- engagement record ---")
    print(json.dumps(json.loads(result.record_json.read_text())["findings"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
