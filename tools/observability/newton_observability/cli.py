"""Command line entry: ``--once`` or bounded ``--interval`` polling."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from .sync import sync_once

DEFAULT_URI = "http://127.0.0.1:18767"


def main(argv: list[str] | None = None) -> int:
    """Run the synchronizer.

    Args:
        argv: Arguments without the program name; defaults to ``sys.argv[1:]``.

    Returns:
        Process exit status: with ``--once`` it is 1 when any snapshot was
        rejected, so callers notice invalid input; polling mode keeps running
        and prints rejections on stderr.
    """
    parser = argparse.ArgumentParser(prog="newton-observability-sync")
    parser.add_argument("--tracking-uri", default=DEFAULT_URI)
    parser.add_argument("--snapshots", type=Path, default=Path(".runtime/observability"))
    parser.add_argument("--state", type=Path, default=Path(".runtime/mlflow-newton/sync-state.json"))
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true", help="synchronize once and exit")
    mode.add_argument("--interval", type=float, help="poll every N seconds")
    parser.add_argument("--max-seconds", type=float, default=3600.0, help="daemon lifetime bound (default 1h)")
    args = parser.parse_args(argv)

    deadline = time.monotonic() + args.max_seconds
    while True:
        report = sync_once(args.tracking_uri, args.snapshots, args.state)
        print(
            f"runs created={report.created_runs} updated={report.updated_runs} skipped={report.skipped_runs} "
            f"traces created={report.created_traces} rejected={len(report.rejected)}",
            flush=True,
        )
        for name, reason in report.rejected:
            print(f"rejected {name}: {reason}", file=sys.stderr, flush=True)
        if args.once:
            return 1 if report.rejected else 0
        if time.monotonic() + args.interval > deadline:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
