"""Explicit ARC batch command; never invoked implicitly by capture close."""

from __future__ import annotations

import argparse
import json
from contextlib import closing
from pathlib import Path

import psycopg2

from batch.arc.processor import ARCPostSessionError, run_arc_post_session
from config import settings


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze a verified blackRabbit session")
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--sponsor-id", required=True)
    parser.add_argument("--site-id", required=True)
    parser.add_argument("--config")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    settings.validate()
    try:
        with closing(psycopg2.connect(settings.DATABASE_URL)) as conn, conn:
            result = run_arc_post_session(
                conn,
                args.session_id,
                args.sponsor_id,
                config_path=args.config,
                site_id=args.site_id,
            )
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(result.artifact, indent=2, allow_nan=False), encoding="utf-8"
            )
        print(
            json.dumps(
                {
                    "analysis_id": result.analysis_id,
                    "event_count": result.event_count,
                    "passed_event_count": result.passed_event_count,
                    "baseline_row_count": result.baseline_row_count,
                }
            )
        )
        return 0
    except (ARCPostSessionError, psycopg2.Error) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
