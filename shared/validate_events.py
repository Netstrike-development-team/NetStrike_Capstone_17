"""Command-line validation for a NetStrike event JSONL ledger."""

from __future__ import annotations

import argparse
from pathlib import Path

from .events import EventContractError, EventLedger


def main() -> int:
    """Validate a JSONL ledger and return a process-compatible status code."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ledger", type=Path, help="Path to a NetStrike event JSONL file")
    args = parser.parse_args()

    try:
        ledger = EventLedger(args.ledger)
    except (OSError, EventContractError) as exc:
        parser.exit(1, f"validation failed: {exc}\n")

    print(f"validated {ledger.event_count} event(s) from {args.ledger}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
