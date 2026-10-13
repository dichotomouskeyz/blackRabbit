"""Verify the headless agent against a retained synthetic backend-smoke session."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    from pydantic_ai import models

    from investigation.__main__ import main as cli
    from investigation.tools import RecordingTools

    models.ALLOW_MODEL_REQUESTS = False
    identity = json.loads(args.receipt.read_text(encoding="utf-8"))["identity"]
    scope = {key: identity[key] for key in ("session_id", "sponsor_id", "site_id")}
    before = RecordingTools(**scope)
    if before.capture_source != "simulated":
        raise RuntimeError("The portfolio smoke requires a simulated recording")
    result = cli(
        [
            "--session-id",
            scope["session_id"],
            "--sponsor-id",
            scope["sponsor_id"],
            "--site-id",
            scope["site_id"],
            "--scripted-demo",
            "--output",
            str(args.output),
        ]
    )
    if result:
        return result
    report = json.loads((args.output / "report.json").read_text(encoding="utf-8"))
    trace = json.loads((args.output / "tool_trace.json").read_text(encoding="utf-8"))
    charts = json.loads((args.output / "charts.json").read_text(encoding="utf-8"))
    after = RecordingTools(**scope)
    if (before.analysis_id, before.artifact_sha256) != (after.analysis_id, after.artifact_sha256):
        raise RuntimeError("Saved ARC report changed during investigation")
    expected = [
        "get_session_summary",
        "list_events",
        "get_recording_quality",
        "inspect_signal_window",
        "get_event_response",
    ]
    if [entry["tool"] for entry in trace] != expected:
        raise RuntimeError("Scripted investigation did not complete the required tool path")
    # Replay just the cited tool reads independently to resolve stored references.
    for entry in trace:
        getattr(after, entry["tool"])(**entry["arguments"])
    for evidence in report["evidence"]:
        if after.evidence[evidence["id"]].model_dump(mode="json") != evidence:
            raise RuntimeError("A report citation did not resolve to the stored value")
    if not charts or report["mode"] != "scripted_demo" or not report["findings"]:
        raise RuntimeError("The scripted demo did not produce evidence and chart data")
    receipt = {
        "mode": "scripted_demo",
        "identity": scope,
        "analysis_id": before.analysis_id,
        "artifact_sha256": before.artifact_sha256,
        "analysis_hash_unchanged": True,
        "resolved_evidence_count": len(report["evidence"]),
        "tool_sequence": expected,
        "chart_count": len(charts),
        "live_model_calls": 0,
    }
    (args.output / "receipt.json").write_text(
        json.dumps(receipt, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(receipt))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
