"""Fail CI on findings, skipped parse/read errors, malformed or empty Bandit reports."""

import argparse
import json
from pathlib import Path

MAX_REPORT_BYTES = 5 * 1024 * 1024


def _unique(pairs):
    fields = {}
    for key, value in pairs:
        if key in fields:
            raise ValueError("duplicate report field")
        fields[key] = value
    return fields


def report_passed(path):
    """Read-only report shape/completeness guard, not a security attestation."""
    try:
        with Path(path).open("rb") as handle:
            content = handle.read(MAX_REPORT_BYTES + 1)
        if len(content) > MAX_REPORT_BYTES:
            return False
        report = json.loads(content, object_pairs_hook=_unique)
        lines = report["metrics"]["_totals"]["loc"]
        return (
            report["errors"] == [] and report["results"] == []
            and isinstance(lines, int) and not isinstance(lines, bool) and lines > 0
        )
    except (OSError, ValueError, KeyError, TypeError, RecursionError):
        return False


class SafeParser(argparse.ArgumentParser):
    """Do not echo accidentally pasted values in invocation errors."""

    def error(self, _message):
        self.exit(2, "Invalid security-report arguments. Use --help.\n")


def main(argv=None):
    """Return a blocking CI exit status without echoing report contents."""
    parser = SafeParser(description=__doc__)
    parser.add_argument("report")
    arguments = parser.parse_args(argv)
    passed = report_passed(arguments.report)
    message = "Security report passed." if passed else (
        "Security report blocked: findings, scan errors or invalid report."
    )
    print(message)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
