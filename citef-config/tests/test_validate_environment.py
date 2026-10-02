import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "validate_environment.py"
SPEC = importlib.util.spec_from_file_location("validate_environment", MODULE_PATH)
validate_environment = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validate_environment)


def valid_manifest():
    hosts = [
        ("CTRL01", "10.77.0.10", "linux", "ssh", ["CTRL01", "IDP01", "HELPDESK01", "CLOUD01", "FILE01"]),
        ("DC01", "10.77.0.11", "windows", "winrm", ["DC01"]),
        ("FIN-WS01", "10.77.0.12", "windows", "winrm", ["FIN-WS01"]),
        ("SPLUNK01", "10.77.0.13", "linux", "ssh", ["SPLUNK01"]),
    ]
    return {
        "schema_version": 1,
        "network": {
            "exercise_cidr": "10.77.0.0/24",
            "management_cidr": "10.77.1.0/24",
            "internet_egress": "deny",
            "dns_servers": ["10.77.0.11"],
            "ntp_servers": ["10.77.0.11"],
            "reverse_dns_zone": "0.77.10.in-addr.arpa",
            "domain_dns_name": "simcorp.test",
            "max_clock_skew_seconds": 60,
            "egress_verified_by": "Range operator",
            "egress_verified_at": "2026-10-01T12:00:00Z",
        },
        "assets": [
            {
                "name": name,
                "address": address,
                "dns_name": f"{name.lower()}.simcorp.test",
                "os_family": os_family,
                "os_image_assumption": "test image",
                "os_version_assumption": "test version",
                "connection": connection,
                "port": 22 if connection == "ssh" else 5986,
                "logical_assets": assets,
                "required_services": ["sshd" if os_family == "linux" else "WinRM"],
            }
            for name, address, os_family, connection, assets in hosts
        ],
        "identity_baseline": {
            "domain_dns_name": "simcorp.test",
            "search_base_dn": "OU=Exercise,DC=simcorp,DC=test",
            "organizational_units": ["Exercise"],
            "groups": ["NetStrike Analysts"],
            "users": [{
                "sam_account_name": "exercise.user",
                "enabled": True,
                "member_of": ["Domain Users", "NetStrike Analysts"],
            }],
        },
        "fixtures": [{"path": "/srv/fixtures/baseline.json", "sha256": "a" * 64}],
        "offline_artifacts": {
            "directory": "offline-bundles/test",
            "controller_source": {"file": "source.tar.gz", "sha256": "1" * 64},
            "python_runtime": {
                "archive": {
                    "file": "netstrike-offline-bundle/runtime/python-runtime.tar.gz",
                    "sha256": "2" * 64,
                },
                "requirements_lock": {
                    "file": "netstrike-offline-bundle/destinations/CTRL01/requirements.lock",
                    "sha256": "3" * 64,
                },
            },
            "universal_forwarder": {
                "version": "10.0.1",
                "linux_deb": {"file": "forwarder.deb", "sha256": "a" * 64},
                "windows_msi": {"file": "forwarder.msi", "sha256": "b" * 64},
                "receiver_ca": {"file": "receiver-ca.pem", "sha256": "c" * 64},
            },
            "sysmon": {
                "version": "test",
                "executable": {"file": "Sysmon64.exe", "sha256": "d" * 64},
                "config": {"file": "sysmon-config.xml", "sha256": "e" * 64},
            },
        },
        "splunk": {
            "rest_url": "https://splunk01.simcorp.test:8089",
            "version": "10.0.1",
            "forwarder_receiver": {"host": "splunk01.simcorp.test", "port": 9997},
            "windows_index": "netstrike",
            "linux_index": "netstrike",
            "required_sources": [
                {
                    "id": "windows_security",
                    "probe_query": 'search index=exercise run_id="{run_id}" source="WinEventLog:Security"',
                    "expected_event_id": "readiness-windows-security-001",
                }
            ],
        },
        "controller": {
            "listen_port": 8443,
            "readiness_url": "https://ctrl01.simcorp.test:8443/api/facilitator/readiness",
            "sso_allowed_origins": ["https://ctrl01.simcorp.test:8443"],
            "tls_certificate": {"file": "ctrl01.pem", "sha256": "4" * 64},
            "tls_ca": {"file": "range-ca.pem", "sha256": "5" * 64},
            "emergency_stop": {
                "verified": True,
                "operator": "Exercise operator",
                "contact_channel": "Range bridge",
                "verified_at": "2026-10-01T12:00:00Z",
            },
        },
        "snapshots": {
            "snapshot_ids": {
                "CTRL01": "ctrl01-clean-v1",
                "DC01": "dc01-clean-v1",
                "FIN-WS01": "fin-ws01-clean-v1",
                "SPLUNK01": "splunk01-clean-v1",
            },
        },
    }


class ValidateEnvironmentTests(unittest.TestCase):
    def test_approved_manifest_passes(self):
        manifest = valid_manifest()
        self.assertEqual(validate_environment.validate_manifest(manifest), manifest)

    def test_example_template_is_fail_closed(self):
        path = Path(__file__).parents[1] / "environment.example.json"
        with self.assertRaisesRegex(validate_environment.ManifestError, "egress_verified_by"):
            validate_environment.load_manifest(path)

    def test_inventory_is_generated_from_approved_targets(self):
        inventory = validate_environment.render_inventory(valid_manifest())
        self.assertIn("ctrl01 ansible_host=10.77.0.10", inventory)
        self.assertIn("[file_store]\nctrl01", inventory)
        self.assertIn("[domain_controllers]\ndc01", inventory)
        self.assertIn("ansible_winrm_scheme=https", inventory)

    def test_duplicate_addresses_are_rejected(self):
        manifest = valid_manifest()
        manifest["assets"][1]["address"] = manifest["assets"][0]["address"]
        with self.assertRaisesRegex(validate_environment.ManifestError, "duplicate host address"):
            validate_environment.validate_manifest(manifest)

    def test_unapproved_or_public_target_is_rejected(self):
        manifest = valid_manifest()
        manifest["assets"][0]["address"] = "203.0.113.10"
        with self.assertRaisesRegex(validate_environment.ManifestError, "RFC 1918"):
            validate_environment.validate_manifest(manifest)

    def test_missing_logical_asset_mapping_is_rejected(self):
        manifest = valid_manifest()
        manifest["assets"][0]["logical_assets"].remove("FILE01")
        with self.assertRaisesRegex(validate_environment.ManifestError, "must map exactly"):
            validate_environment.validate_manifest(manifest)

    def test_secret_fields_are_rejected(self):
        manifest = valid_manifest()
        manifest["splunk"]["token"] = "should-not-be-here"
        with self.assertRaisesRegex(validate_environment.ManifestError, "must not contain credentials"):
            validate_environment.validate_manifest(manifest)

    def test_snapshot_inventory_must_cover_every_vm(self):
        manifest = valid_manifest()
        del manifest["snapshots"]["snapshot_ids"]["DC01"]
        with self.assertRaisesRegex(validate_environment.ManifestError, "every physical host"):
            validate_environment.validate_manifest(manifest)

    def test_malformed_logical_asset_fails_with_validation_error(self):
        manifest = valid_manifest()
        manifest["assets"][0]["logical_assets"] = [{}]
        with self.assertRaisesRegex(validate_environment.ManifestError, "logical_assets"):
            validate_environment.validate_manifest(manifest)

    def test_identity_domain_must_be_a_string(self):
        manifest = valid_manifest()
        manifest["identity_baseline"]["domain_dns_name"] = None
        with self.assertRaisesRegex(validate_environment.ManifestError, "domain_dns_name"):
            validate_environment.validate_manifest(manifest)

    def test_embedded_splunk_credentials_are_rejected(self):
        manifest = valid_manifest()
        manifest["splunk"]["rest_url"] = "https://user:password@splunk01.simcorp.test:8089"
        with self.assertRaisesRegex(validate_environment.ManifestError, "must not contain credentials"):
            validate_environment.validate_manifest(manifest)

    def test_controller_readiness_requires_https(self):
        manifest = valid_manifest()
        manifest["controller"]["readiness_url"] = "http://ctrl01.simcorp.test/api/facilitator/readiness"
        with self.assertRaisesRegex(validate_environment.ManifestError, "does not match '\\^https://"):
            validate_environment.validate_manifest(manifest)

    def test_schema_rejects_unknown_fields(self):
        manifest = valid_manifest()
        manifest["network"]["unexpected"] = "not approved"
        with self.assertRaisesRegex(validate_environment.ManifestError, "unexpected"):
            validate_environment.validate_manifest(manifest)

    def test_schema_rejects_invalid_hashes(self):
        manifest = valid_manifest()
        manifest["offline_artifacts"]["controller_source"]["sha256"] = "not-a-hash"
        with self.assertRaisesRegex(validate_environment.ManifestError, "sha256"):
            validate_environment.validate_manifest(manifest)

    def test_inventory_generation_revalidates_manifest(self):
        manifest = valid_manifest()
        manifest["network"]["internet_egress"] = "allow"
        with self.assertRaisesRegex(validate_environment.ManifestError, "internet_egress"):
            validate_environment.render_inventory(manifest)

    def test_disabled_baseline_identity_is_representable(self):
        manifest = valid_manifest()
        manifest["identity_baseline"]["users"][0]["enabled"] = False
        self.assertEqual(validate_environment.validate_manifest(manifest), manifest)


if __name__ == "__main__":
    unittest.main()
