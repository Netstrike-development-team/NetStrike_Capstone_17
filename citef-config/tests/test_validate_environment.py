import json
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
            "dns_servers": ["10.77.0.11"],
            "ntp_servers": ["10.77.0.11"],
            "reverse_dns_zone": "0.77.10.in-addr.arpa",
            "domain_dns_name": "simcorp.test",
            "max_clock_skew_seconds": 60,
        },
        "assets": [
            {
                "name": name,
                "address": address,
                "dns_name": f"{name.lower()}.simcorp.test",
                "os_family": os_family,
                "connection": connection,
                "port": 22 if connection == "ssh" else 5985,
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
        "offline_artifacts": {
            "directory": "offline-bundles/test",
            "universal_forwarder": {
                "version": "10.0.1",
                "linux_deb": {"file": "forwarder.deb", "sha512": "a" * 128},
                "windows_msi": {
                    "file": "windows/splunkforwarder-10.0.1-c486717c322b-windows-x64.msi",
                    "sha512": "b" * 128,
                },
                "receiver_ca": {"file": "receiver-ca.pem", "sha256": "c" * 64},
            },
            "sysmon": {
                "version": "test",
                "archive": {"file": "sysmon/Sysmon.zip", "sha256": "d" * 64},
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
                    "probe_query": 'search index=netstrike run_id="{run_id}" source="WinEventLog:Security"',
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
        },
    }


class ValidateEnvironmentTests(unittest.TestCase):
    def test_approved_manifest_passes(self):
        manifest = valid_manifest()
        self.assertEqual(validate_environment.validate_manifest(manifest), manifest)

    def test_splunk_dns_name_can_be_customized(self):
        manifest = valid_manifest()
        manifest["assets"][3]["dns_name"] = "splunk-lab.simcorp.test"
        manifest["splunk"]["forwarder_receiver"]["host"] = "splunk-lab.simcorp.test"
        manifest["splunk"]["rest_url"] = "https://splunk-lab.simcorp.test:8089"
        self.assertEqual(validate_environment.validate_manifest(manifest), manifest)

    def test_splunk_dns_name_must_be_in_the_authoritative_zone(self):
        manifest = valid_manifest()
        manifest["assets"][3]["dns_name"] = "192.168.0.234"
        manifest["splunk"]["forwarder_receiver"]["host"] = "192.168.0.234"
        with self.assertRaisesRegex(validate_environment.ManifestError, "fully qualified name within"):
            validate_environment.validate_manifest(manifest)

    def test_certificates_are_optional(self):
        manifest = valid_manifest()
        del manifest["offline_artifacts"]["universal_forwarder"]["receiver_ca"]
        del manifest["controller"]["tls_certificate"]
        del manifest["controller"]["tls_ca"]
        self.assertEqual(validate_environment.validate_manifest(manifest), manifest)

    def test_controller_certificate_requires_its_ca(self):
        manifest = valid_manifest()
        del manifest["controller"]["tls_ca"]
        with self.assertRaisesRegex(validate_environment.ManifestError, "provided together"):
            validate_environment.validate_manifest(manifest)

    def test_example_template_is_fail_closed(self):
        path = Path(__file__).parents[1] / "environment.example.json"
        with self.assertRaisesRegex(validate_environment.ManifestError, "Manifest schema validation failed"):
            validate_environment.load_manifest(path)

    def test_example_readiness_probe_uses_configured_windows_index(self):
        path = Path(__file__).parents[1] / "environment.example.json"
        manifest = json.loads(path.read_text())
        probe = next(
            source for source in manifest["splunk"]["required_sources"]
            if source["id"] == "windows_security"
        )
        self.assertIn(
            f"index={manifest['splunk']['windows_index']}",
            probe["probe_query"],
        )

    def test_inventory_is_generated_from_approved_targets(self):
        inventory = validate_environment.render_inventory(valid_manifest())
        self.assertIn("ctrl01 ansible_host=10.77.0.10", inventory)
        self.assertIn("[file_store]\nctrl01", inventory)
        self.assertIn("[domain_controllers]\ndc01", inventory)
        self.assertIn(
            "ansible_connection=winrm ansible_winrm_transport=ntlm "
            "ansible_port=5985 ansible_winrm_scheme=http",
            inventory,
        )
        self.assertNotIn("ansible_user=", inventory)
        self.assertNotIn("ansible_password=", inventory)
        self.assertNotIn("ansible_become_password=", inventory)

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

    def test_splunk_rest_url_accepts_http_and_https(self):
        manifest = valid_manifest()
        manifest["splunk"]["rest_url"] = "http://splunk01.simcorp.test:8089"
        self.assertEqual(validate_environment.validate_manifest(manifest), manifest)

    def test_splunk_rest_url_rejects_other_schemes(self):
        manifest = valid_manifest()
        manifest["splunk"]["rest_url"] = "ftp://splunk01.simcorp.test:8089"
        with self.assertRaisesRegex(validate_environment.ManifestError, "rest_url"):
            validate_environment.validate_manifest(manifest)

    def test_schema_rejects_unknown_fields(self):
        manifest = valid_manifest()
        manifest["network"]["unexpected"] = "not approved"
        with self.assertRaisesRegex(validate_environment.ManifestError, "unexpected"):
            validate_environment.validate_manifest(manifest)

    def test_schema_rejects_fixture_configuration(self):
        manifest = valid_manifest()
        manifest["fixtures"] = []
        with self.assertRaisesRegex(validate_environment.ManifestError, "fixtures"):
            validate_environment.validate_manifest(manifest)

    def test_schema_rejects_invalid_hashes(self):
        manifest = valid_manifest()
        manifest["offline_artifacts"]["sysmon"]["archive"]["sha256"] = "not-a-hash"
        with self.assertRaisesRegex(validate_environment.ManifestError, "sha256"):
            validate_environment.validate_manifest(manifest)

    def test_schema_rejects_invalid_forwarder_sha512(self):
        manifest = valid_manifest()
        manifest["offline_artifacts"]["universal_forwarder"]["windows_msi"]["sha512"] = "not-a-hash"
        with self.assertRaisesRegex(validate_environment.ManifestError, "sha512"):
            validate_environment.validate_manifest(manifest)

    def test_schema_rejects_removed_artifact_fields(self):
        for field in ("controller_source", "python_runtime"):
            with self.subTest(field=field):
                manifest = valid_manifest()
                manifest["offline_artifacts"][field] = {}
                with self.assertRaisesRegex(validate_environment.ManifestError, field):
                    validate_environment.validate_manifest(manifest)

    def test_forwarder_does_not_accept_sha256(self):
        manifest = valid_manifest()
        manifest["offline_artifacts"]["universal_forwarder"]["linux_deb"]["sha256"] = "a" * 64
        with self.assertRaisesRegex(validate_environment.ManifestError, "sha256"):
            validate_environment.validate_manifest(manifest)

    def test_forwarder_file_path_must_remain_relative(self):
        manifest = valid_manifest()
        manifest["offline_artifacts"]["universal_forwarder"]["linux_deb"]["file"] = "../forwarder.deb"
        with self.assertRaisesRegex(validate_environment.ManifestError, "safe relative path"):
            validate_environment.validate_manifest(manifest)

    def test_sysmon_archive_must_use_licensed_staging_directory(self):
        manifest = valid_manifest()
        manifest["offline_artifacts"]["sysmon"]["archive"]["file"] = "Sysmon.zip"
        with self.assertRaisesRegex(validate_environment.ManifestError, "must be sysmon/Sysmon.zip"):
            validate_environment.validate_manifest(manifest)

    def test_windows_forwarder_msi_must_use_licensed_staging_directory(self):
        manifest = valid_manifest()
        manifest["offline_artifacts"]["universal_forwarder"]["windows_msi"]["file"] = "forwarder.msi"
        with self.assertRaisesRegex(validate_environment.ManifestError, "must be the Windows MSI"):
            validate_environment.validate_manifest(manifest)

    def test_inventory_generation_rejects_public_network(self):
        manifest = valid_manifest()
        manifest["network"]["exercise_cidr"] = "203.0.113.0/24"
        with self.assertRaisesRegex(validate_environment.ManifestError, "RFC 1918"):
            validate_environment.render_inventory(manifest)

    def test_disabled_baseline_identity_is_representable(self):
        manifest = valid_manifest()
        manifest["identity_baseline"]["users"][0]["enabled"] = False
        self.assertEqual(validate_environment.validate_manifest(manifest), manifest)


if __name__ == "__main__":
    unittest.main()
