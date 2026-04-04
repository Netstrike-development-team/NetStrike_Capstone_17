#!/usr/bin/env python3
"""
Test suite for Module 07 - Ransomware Simulation

Tests the simplified main.py entry point and event schema conformance.
"""

import sys
import unittest
from pathlib import Path
from datetime import datetime
import tempfile
import shutil

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from main import run, run_standalone


class TestRansomwareSimulationRun(unittest.TestCase):
    """Test the main run() function for orchestrator mode"""
    
    def setUp(self):
        """Set up test configuration"""
        self.test_config = {
            "vcenter": {
                "host": "vcenter.test.local",
                "username": "test_admin",
                "password": "test_password",
                "port": 443
            },
            "target_vms": ["TEST-VM-01", "TEST-VM-02"],
            "ransom": {
                "amount": "$100,000",
                "currency": "Bitcoin",
                "attacker_email": "test@example.com",
                "deadline_days": 7
            },
            "file_extensions": [".docx", ".xlsx", ".pdf"],
            "simulation_mode": True
        }
    
    def test_run_returns_5_events(self):
        """Test that run() returns 5 events (one per phase)"""
        events = run(self.test_config)
        self.assertIsInstance(events, list)
        self.assertEqual(len(events), 5, "Should emit exactly 5 events (5 phases)")
    
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
            self.assertEqual(event["phase"], 7)  # All events are phase 7
            
            # Validate timestamp format (ISO 8601)
            try:
                datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00"))
            except ValueError:
                self.fail(f"Invalid timestamp format: {event['timestamp']}")
    
    def test_events_have_correct_source_module(self):
        """Test that all events have correct source module"""
        events = run(self.test_config)
        
        for event in events:
            self.assertEqual(event["source_module"], "07-ransomware-sim")
    
    def test_events_have_mitre_techniques(self):
        """Test that events reference MITRE ATT&CK techniques"""
        events = run(self.test_config)
        expected_techniques = ["T1469", "T1526", "T1490", "T1486", "T1486"]
        
        for i, event in enumerate(events):
            self.assertEqual(event["technique_id"], expected_techniques[i],
                f"Event {i} should use technique {expected_techniques[i]}")
    
    def test_event_sequence(self):
        """Test that events follow the correct sequence"""
        events = run(self.test_config)
        
        expected_tactics = ["initial-access", "reconnaissance", "defense-evasion", "impact", "impact"]
        
        for i, event in enumerate(events):
            self.assertEqual(event["tactic"], expected_tactics[i],
                f"Event {i} should have tactic {expected_tactics[i]}")
    
    def test_flag_7_in_final_event(self):
        """Test that Flag 7 is triggered in the final event"""
        events = run(self.test_config)
        final_event = events[-1]
        
        self.assertIsNotNone(final_event.get("flag_triggered"),
            "Final event should trigger a flag")
        self.assertIn("Flag 7", final_event["flag_triggered"],
            "Final event should trigger Flag 7")
    
    def test_config_with_custom_vms(self):
        """Test configuration with custom target VMs"""
        config = self.test_config.copy()
        config["target_vms"] = ["CUSTOM-VM-01", "CUSTOM-VM-02", "CUSTOM-VM-03"]
        
        events = run(config)
        self.assertEqual(len(events), 5)
        
        # Check that VMs are referenced in raw_data
        second_event = events[1]  # VM enumeration event
        self.assertIn("vm_count", second_event["raw_data"])
        self.assertEqual(second_event["raw_data"]["vm_count"], 3)
    
    def test_ransom_params_in_final_event(self):
        """Test that ransom parameters are in final event"""
        config = self.test_config.copy()
        config["ransom"]["amount"] = "$750,000"
        config["ransom"]["attacker_email"] = "custom@example.com"
        
        events = run(config)
        final_event = events[-1]
        
        self.assertEqual(final_event["raw_data"]["ransom_amount"], "$750,000")
        self.assertEqual(final_event["raw_data"]["attacker_contact"], "custom@example.com")


class TestRansomwareStandalone(unittest.TestCase):
    """Test the standalone mode for local file encryption"""
    
    def setUp(self):
        """Create temporary test directory"""
        self.test_dir = tempfile.mkdtemp()
    
    def tearDown(self):
        """Clean up temporary directory"""
        if Path(self.test_dir).exists():
            shutil.rmtree(self.test_dir)
    
    def test_standalone_returns_5_events(self):
        """Test that run_standalone() returns 5 events"""
        events = run_standalone(self.test_dir)
        self.assertEqual(len(events), 5)
    
    def test_standalone_creates_fake_files(self):
        """Test that standalone mode creates fake files"""
        events = run_standalone(self.test_dir)
        
        test_path = Path(self.test_dir)
        files = list(test_path.glob("important_file_*"))
        self.assertGreater(len(files), 0, "Should create fake files")
    
    def test_standalone_creates_encryption_markers(self):
        """Test that standalone mode creates .RANSOMHUB markers"""
        events = run_standalone(self.test_dir)
        
        test_path = Path(self.test_dir)
        markers = list(test_path.glob("*.RANSOMHUB"))
        self.assertGreater(len(markers), 0, "Should create .RANSOMHUB markers")
    
    def test_standalone_creates_ransom_note(self):
        """Test that standalone mode creates ransom note"""
        events = run_standalone(self.test_dir)
        
        ransom_note = Path(self.test_dir) / "README_RANSOMHUB.txt"
        self.assertTrue(ransom_note.exists(), "Should create ransom note file")
        
        content = ransom_note.read_text()
        self.assertIn("RANSOMHUB", content)
        self.assertIn("contact@ransomhub.local", content)
    
    def test_standalone_events_match_schema(self):
        """Test that standalone events match the schema"""
        events = run_standalone(self.test_dir)
        
        required_fields = [
            "event_id", "timestamp", "phase", "technique_id",
            "tactic", "description", "source_module", "flag_triggered",
            "raw_data"
        ]
        
        for event in events:
            for field in required_fields:
                self.assertIn(field, event)
            
            self.assertIsInstance(event["event_id"], str)
            self.assertIsInstance(event["timestamp"], str)


class TestEventSchema(unittest.TestCase):
    """Test conformance to the NetStrike event schema"""
    
    def test_schema_validation(self):
        """Test that events match schemas/event.json schema"""
        # This would ideally load schemas/event.json and validate against it
        # For now, this is a placeholder for schema validation tests
        pass


if __name__ == "__main__":
    unittest.main()
