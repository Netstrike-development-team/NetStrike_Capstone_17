import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta

# Import functions from your module
import ad_enum_simulated_escalation as module


class TestHelperFunctions(unittest.TestCase):

    def test_filetime_to_datetime_valid(self):
        # FILETIME for 2020-01-01
        ft = 132199584000000000
        dt = module.filetime_to_datetime(ft)
        self.assertIsInstance(dt, datetime)

    def test_filetime_to_datetime_zero(self):
        self.assertIsNone(module.filetime_to_datetime(0))

    def test_has_flag(self):
        flag = 0x0002
        self.assertTrue(module.has_flag(flag, flag))
        self.assertFalse(module.has_flag(0x0000, flag))


class TestCSVExport(unittest.TestCase):

    @patch("builtins.open")
    def test_export_csv(self, mock_open):
        rows = [{"a": 1, "b": 2}]
        module.export_csv("test.csv", ["a", "b"], rows)
        mock_open.assert_called_once()


class TestSimulatedEscalation(unittest.TestCase):

    @patch("ad_enum_simulated_escalation.logger")
    def test_simulated_escalation_logs(self, mock_logger):
        new_stage = module.simulate_escalation("PRIVILEGED_USER", "simcorp\\svc-admin-tier1")
        self.assertEqual(new_stage, "PRIVILEGED_USER")
        mock_logger.info.assert_called()


class TestSafeSearch(unittest.TestCase):

    def test_safe_search_handles_exception(self):
        conn = MagicMock()
        conn.search.side_effect = Exception("LDAP error")
        results = module.safe_search(conn, "DC=simcorp,DC=com", "(objectClass=user)", [])
        self.assertEqual(results, [])


if __name__ == "__main__":
    unittest.main()