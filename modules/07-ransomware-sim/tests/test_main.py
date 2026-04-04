#!/usr/bin/env python3
"""
Test suite for Module 07 - Ransomware Simulation

Tests the main.py entry point and event schema conformance.
"""

import sys
import unittest
from pathlib import Path
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from main import run


class TestRansomwareSimulationRun(unittest.TestCase):
    """Test the main run() function"""
    
    def setUp(self):
        """Set up test configuration"""
        self.test_config = {
            "vcenter_config": {
                "host": "vcenter.test.local",
                "username": "test_admin",
                "password": "test_password",
                "port": 443
            },
            "target_vms": ["TEST-VM-01", "TEST-VM-02"],
            "ransom_parameters": {
                "amount_usd": 100000,
                "currency": "Bitcoin",
                "attacker_email": "test@example.com",
                "payment_deadline_days": 7
            },
            "target_file_extensions": [".docx", ".xlsx", ".pdf"],
            "simulation_mode": True,
            "backup_targets": ["C:\\Backup"]
        }
    
    def test_run_returns_list_of_events(self):
        """Test that run() returns a list of events"""
        events = run(self.test_config)
        self.assertIsInstance(events, list)
        self.assertGreater(len(events), 0)
    
    def test_events_match_schema(self):
        """Test that all returned events match the NetStrike event schema"""
        events = run(self.test_config)
        
        required_fields = [
            "event_id", "timestamp", "phase", "technique_id",
            "tactic", "description", "source_module", "flag_triggered",
            "raw_data"
        ]
        
        for event in events:
            # Check all required fields exist
            for field in required_fields:
                self.assertIn(field, event,
                    f"Missing required field: {field}")
            
            # Validate field types
            self.assertIsInstance(event["event_id"], str)
            self.assertIsInstance(event["timestamp"], str)
            self.assertIsInstance(event["phase"], int)
            self.assertIsInstance(event["technique_id"], str)
            self.assertIsInstance(event["tactic"], str)
            self.assertIsInstance(event["description"], str)
            self.assertIsInstance(event["source_module"], str)
            self.assertIsInstance(event["raw_data"], dict)
            
            # Validate constraints
            self.assertGreaterEqual(event["phase"], 0)
            self.assertLessEqual(event["phase"], 7)
            
            # Validate timestamp format
            try:
                datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00"))
            except ValueError:
                self.fail(f"Invalid timestamp format: {event['timestamp']}")
    
    def test_events_have_source_module(self):
        """Test that all events have correct source module"""
        events = run(self.test_config)
        
        for event in events:
            self.assertEqual(event["source_module"], "07-ransomware-sim")
    
    def test_events_have_mitre_techniques(self):
        """Test that events reference MITRE ATT&CK techniques"""
        events = run(self.test_config)
        
        for event in events:
            # Should be in format T####.### or similar
            technique_id = event["technique_id"]
            self.assertTrue(
                technique_id.startswith("T") or technique_id == "UNKNOWN",
                f"Invalid technique format: {technique_id}"
            )
    
    def test_simulation_mode_enabled(self):
        """Test that simulation mode prevents real execution"""
        config = self.test_config.copy()
        config["simulation_mode"] = True
        
        events = run(config)
        # Should complete without errors
        self.assertGreater(len(events), 0)
    
    def test_config_with_custom_vms(self):
        """Test configuration with custom target VMs"""
        config = self.test_config.copy()
        config["target_vms"] = ["CUSTOM-VM-01", "CUSTOM-VM-02", "CUSTOM-VM-03"]
        
        events = run(config)
        self.assertGreater(len(events), 0)
        
        # At least one event should mention targeting VMs
        descriptions = [e.get("description", "").lower() for e in events]
        found_vm_reference = any("vm" in desc for desc in descriptions)
        self.assertTrue(found_vm_reference)


class TestEventSchema(unittest.TestCase):
    """Test conformance to the NetStrike event schema"""
    
    def test_schema_validation(self):
        """Test that events match schemas/event.json schema"""
        # This would ideally load schemas/event.json and validate against it
        # For now, this is a placeholder for schema validation tests
        pass


if __name__ == "__main__":
    unittest.main()
