"""Static checks for the versioned Splunk content (no Splunk instance needed)."""

import csv
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAFF = ROOT / "staff" / "netstrike_staff"
PARTICIPANT = ROOT / "participant" / "netstrike_participant"
FORWARDER = ROOT / "forwarder" / "netstrike_app_events_inputs"


def parse_conf(path):
    """Parse a Splunk .conf file, honouring trailing-backslash continuations."""
    stanzas, current, pending = {}, None, ""
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = pending + raw.strip()
        pending = ""
        if line.endswith("\\"):
            pending = line[:-1].rstrip() + " "
            continue
        if not line or line.startswith("#"):
            continue
        header = re.fullmatch(r"\[(.*)\]", line)
        if header:
            current = stanzas.setdefault(header.group(1), {})
        else:
            key, _, value = line.partition("=")
            if current is None or not _:
                raise AssertionError(f"{path}: unparseable line {line!r}")
            current[key.strip()] = value.strip()
    return stanzas


class SplunkConfigTests(unittest.TestCase):
    def test_every_conf_file_parses(self):
        for path in ROOT.rglob("*.conf"):
            with self.subTest(path=path):
                self.assertTrue(parse_conf(path))

    def test_indexes_have_one_day_retention(self):
        indexes = parse_conf(STAFF / "default" / "indexes.conf")
        self.assertEqual({"netstrike", "netstrike_staff"}, set(indexes))
        for name, values in indexes.items():
            with self.subTest(index=name):
                self.assertEqual("86400", values["frozenTimePeriodInSecs"])
                self.assertEqual("86400", values["maxHotSpanSecs"])

    def test_participant_role_is_explicitly_limited(self):
        roles = parse_conf(STAFF / "default" / "authorize.conf")
        participant = roles["role_netstrike_participant"]
        self.assertEqual("netstrike", participant["srchIndexesAllowed"])
        self.assertEqual("netstrike", participant["srchIndexesDefault"])
        self.assertNotIn("importRoles", participant)
        facilitator = roles["role_netstrike_facilitator"]
        self.assertIn("netstrike_staff", facilitator["srchIndexesAllowed"])

    def test_participant_app_never_touches_staff_data(self):
        text = "".join(
            path.read_text(encoding="utf-8")
            for path in (PARTICIPANT / "default").glob("*.conf")
        )
        for forbidden in ("netstrike_staff", "_internal", "netstrike:event:v1",
                          "inputlookup", "| rest", "malicious", "suspicious"):
            self.assertNotIn(forbidden, text)

    def test_apps_are_not_readable_across_the_boundary(self):
        staff = (STAFF / "metadata" / "default.meta").read_text(encoding="utf-8")
        self.assertNotIn("netstrike_participant", staff)
        participant = (PARTICIPANT / "metadata" / "default.meta").read_text(encoding="utf-8")
        self.assertIn("netstrike_participant", participant)

    def test_monitor_selects_only_committed_batches(self):
        monitor = parse_conf(FORWARDER / "default" / "inputs.conf")[
            "monitor:///var/lib/netstrike/event-spool"
        ]
        keep = re.compile(monitor["whitelist"])
        drop = re.compile(monitor["blacklist"])
        base = "/var/lib/netstrike/event-spool/"
        batch = "batch-" + "1".zfill(20) + "-" + "500".zfill(20)
        good = f"{base}{batch}/events.jsonl"
        self.assertTrue(keep.search(good) and not drop.search(good))
        for bad in (f"{base}HEAD.json", f"{base}{batch}/manifest.json",
                    f"{base}.pending-abc/events.jsonl", f"{base}.head-abc"):
            self.assertFalse(keep.search(bad) and not drop.search(bad), bad)
        self.assertEqual("false", monitor["followSymlink"])
        self.assertEqual("netstrike_staff", monitor["index"])
        self.assertNotEqual("batch", monitor.get("method"))

    def test_expected_sources_lookup_is_well_formed(self):
        with (STAFF / "lookups" / "netstrike_expected_sources.csv").open(encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        ids = [row["source_id"] for row in rows]
        self.assertEqual(len(ids), len(set(ids)))
        for row in rows:
            self.assertIn(row["required"], {"0", "1"})
            self.assertGreater(int(row["max_age_seconds"]), 0)
        for required in ("windows_security", "windows_powershell", "windows_sysmon"):
            self.assertIn(required, ids)

    def test_learner_monitor_has_separate_path_index_and_contract(self):
        inputs = parse_conf(FORWARDER / "default" / "inputs.conf")
        learner = inputs["monitor:///var/lib/netstrike/learner-event-spool"]
        staff = inputs["monitor:///var/lib/netstrike/event-spool"]
        self.assertEqual("netstrike", learner["index"])
        self.assertEqual("netstrike:learner:audit:v1", learner["sourcetype"])
        self.assertNotEqual(staff["sourcetype"], learner["sourcetype"])
        for key in ("whitelist", "blacklist", "followSymlink", "crcSalt"):
            self.assertEqual(staff[key], learner[key])
        for folder in (FORWARDER, STAFF):
            stanza = parse_conf(folder / "default" / "props.conf")[learner["sourcetype"]]
            self.assertEqual("UTC", stanza["TZ"])
        self.assertEqual("timestamp", parse_conf(FORWARDER / "default" / "props.conf")[learner["sourcetype"]]["TIMESTAMP_FIELDS"])
        searches = parse_conf(PARTICIPANT / "default" / "savedsearches.conf")
        self.assertIn("Investigate - SimCorp audit timeline", searches)
        self.assertIn("`netstrike_simcorp_audit`", searches["Investigate - SimCorp audit timeline"]["search"])

    def test_no_secrets_committed(self):
        pattern = re.compile(r"(token|password|pass4SymmKey|sslPassword|hec)\s*=", re.I)
        for path in ROOT.rglob("*"):
            if path.is_file() and path.suffix in {".conf", ".csv", ".meta"}:
                with self.subTest(path=path):
                    self.assertIsNone(pattern.search(path.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
