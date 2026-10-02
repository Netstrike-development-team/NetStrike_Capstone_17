"""Read one exported run bundle and reproduce its AAR entirely offline."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Direct-file CLI execution must add the repository before importing its packages.
# pylint: disable=wrong-import-position
from orchestrator.aar import (
    build_report,
    participant_feedback,
    render_markdown,
)
# pylint: enable=wrong-import-position


def main(argv=None) -> int:
    """Print a report to stdout; no writes, server, credentials or network required."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument(
        "--format", choices=("markdown", "json", "feedback"), default="markdown"
    )
    arguments = parser.parse_args(argv)
    try:
        if arguments.bundle.stat().st_size > 20 * 1024 * 1024:
            raise ValueError("bundle exceeds 20 MiB review limit")
        bundle = json.loads(arguments.bundle.read_text(encoding="utf-8"))
        report = build_report(bundle)
        if arguments.format == "markdown":
            print(render_markdown(report), end="")
        else:
            payload = (
                participant_feedback(report)
                if arguments.format == "feedback"
                else report
            )
            print(json.dumps(payload, indent=2, sort_keys=True))
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"Cannot generate AAR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
