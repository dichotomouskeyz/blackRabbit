"""Headless investigation CLI; no model credentials needed for scripted demos."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from config import settings
from investigation.models import InvestigationError


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Investigate a completed blackRabbit recording")
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--sponsor-id", default=settings.API_SPONSOR_ID)
    parser.add_argument("--site-id", default=settings.API_SITE_ID)
    parser.add_argument(
        "--question",
        default="What changed around the first marker, and what limits interpretation?",
    )
    parser.add_argument(
        "--scripted-demo",
        action="store_true",
        help="Run a scripted FunctionModel with synthetic data and no model/network request",
    )
    parser.add_argument("--output", type=Path, help="Directory for report, charts and tool trace")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        # Lazy import keeps --help available without the agent extra installed.
        from investigation.demo import build_demo_model
        from investigation.runtime import run_investigation
        from investigation.tools import RecordingTools
    except ImportError:
        print(
            json.dumps(
                {"error": "agent_not_installed", "message": "Install with uv sync --extra agent"}
            )
        )
        return 2
    try:
        if not args.sponsor_id or not args.site_id:
            raise InvestigationError("tenancy_not_configured", "Provide sponsor and site IDs", 503)
        tools = RecordingTools(args.session_id, args.sponsor_id, args.site_id)
        result = asyncio.run(
            run_investigation(
                args.question,
                tools,
                model=build_demo_model() if args.scripted_demo else None,
                mode="scripted_demo" if args.scripted_demo else "configured_model",
            )
        )
        report = result.report.model_dump(mode="json")
        payload = {"report": report, "tool_trace": result.trace, "charts": result.charts}
        if args.output:
            args.output.mkdir(parents=True, exist_ok=True)
            for name, value in payload.items():
                (args.output / f"{name}.json").write_text(
                    json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8"
                )
            (args.output / "report.md").write_text(markdown_report(report), encoding="utf-8")
            print(
                json.dumps(
                    {
                        "mode": report["mode"],
                        "analysis_id": report["analysis_id"],
                        "output": str(args.output),
                        "tool_calls": len(result.trace),
                        "chart_count": len(result.charts),
                    }
                )
            )
        else:
            print(json.dumps(payload, indent=2, allow_nan=False))
        return 0
    except InvestigationError as exc:
        print(json.dumps({"error": exc.code, "message": str(exc)}), file=sys.stderr)
        return 1


def markdown_report(report: dict) -> str:
    lines = [
        "# Recording investigation",
        "",
        f"Mode: `{report['mode']}`",
        "",
        f"Session: `{report['session_id']}`",
        f"Analysis: `{report['analysis_id']}`",
        "",
        report["summary"],
        "",
    ]
    if report["mode"] == "scripted_demo":
        lines += [
            "This is a scripted tool-loop demonstration using synthetic data. "
            "No live language model was used.",
            "",
        ]
    for finding in report["findings"]:
        lines += [finding["text"], "Evidence: " + ", ".join(finding["evidence_ids"]), ""]
    for heading, key in [
        ("Quality limitations", "quality_limitations"),
        ("Unresolved questions", "unresolved_questions"),
    ]:
        if report[key]:
            lines += [f"## {heading}", "", *[f"- {x}" for x in report[key]], ""]
    lines += ["## Evidence", ""]
    for evidence in report["evidence"]:
        lines.append(
            f"- `{evidence['id']}`: {evidence['metric']} = "
            f"{json.dumps(evidence['value'], ensure_ascii=False)} {evidence['units'] or ''}"
        )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
