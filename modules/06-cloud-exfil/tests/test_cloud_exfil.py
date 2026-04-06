import unittest
import json
from pathlib import Path
import sys

import cloud_exfil as module

class TestCloudExfil(unittest.TestCase):

    def test_iam_authentication_success(self):
        iam = module.MockIAM()
        self.assertTrue(iam.authenticate("SIMCORPUSER123"))

    def test_iam_authentication_failure(self):
        iam = module.MockIAM()
        self.assertFalse(iam.authenticate("WRONGKEY"))

    def test_iam_create_backdoor_user(self):
        iam = module.MockIAM()
        iam.create_user("evil_user")
        self.assertIn("evil_user", iam.users)
        self.assertEqual(iam.users["evil_user"]["roles"], ["backdoor"])

    def test_s3_bucket_listing(self):
        s3 = module.MockS3()
        buckets = s3.list_buckets()
        self.assertIn("customer-data-prod", buckets)

    def test_s3_list_objects(self):
        s3 = module.MockS3()
        objects = s3.list_objects("customer-data-prod")
        self.assertEqual(len(objects), 2)

    def test_simulation_runs_without_error(self):
        try:
            module.run()
        except Exception as e:
            self.fail(f"Simulation raised an exception: {e}")