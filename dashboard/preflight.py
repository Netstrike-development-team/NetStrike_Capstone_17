"""Offline configuration inspection; no deployment, server, SQLite or decoy writes."""

import argparse
import json


class SafeParser(argparse.ArgumentParser):
    """Invalid arguments must not echo accidentally pasted private values."""

    def error(self, message):
        self.exit(2, "Invalid preflight arguments. Use --help.\n")


def main(argv=None):
    """Return zero only for valid configuration, never for range readiness."""
    parser = SafeParser(description=__doc__)
    parser.add_argument("--expect-scope", choices=("identity", "cloud", "full-play"))
    arguments = parser.parse_args(argv)
    try:
        from .configuration import inspect_configuration  # pylint: disable=import-outside-toplevel
        report, _configuration = inspect_configuration(expected_scope=arguments.expect_scope)
    except Exception:  # Missing/incompatible offline source/dependencies are safe blockers.
        report = {"scope": "application_configuration_only", "configuration_valid": False,
                  "read_only": True, "external_readiness_verified": False,
                  "runtime_readiness_verified": False, "blockers": ["inspection_unavailable"]}
    print(json.dumps(report, sort_keys=True, indent=2))
    return 0 if report["configuration_valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
