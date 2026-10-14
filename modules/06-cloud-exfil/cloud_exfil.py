import time
import json
import logging
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Output folder structure
# ---------------------------------------------------------------------------

OUTPUT_DIR = Path("output")
LOG_DIR = OUTPUT_DIR / "logs"
EXFIL_DATA_DIR = OUTPUT_DIR / "userdata"

LOG_DIR.mkdir(parents=True, exist_ok=True)
EXFIL_DATA_DIR.mkdir(parents=True, exist_ok=True)

LOG_FILE = LOG_DIR / "cloud_pivot_and_exfil_sim.log"

# -------------------------------------------------------------------
# Logging Configuration
# -------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("cloud_pivot_and_exfil_sim.log"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# -------------------------------------------------------------------
# Simulated AWS-like environment (CITEF Cloud Exfiltration Module)
# -------------------------------------------------------------------

class MockIAM:
    def __init__(self):
        self.users = {"user": {"keys": ["SIMCORPUSER123"], "roles": ["standard_user"]}}

    def authenticate(self, access_key):
        return access_key in self.users["user"]["keys"]

    def create_user(self, username):
        self.users[username] = {"keys": ["NEWKEY123"], "roles": ["backdoor"]}
        logger.info(f"Created backdoor IAM user: {username}")
        return username


class MockS3:
    def __init__(self):
        self.buckets = {
            "customer-data-prod": [
                {"filename": "user_001.json", "size_kb": 12},
                {"filename": "user_002.json", "size_kb": 14},
            ],
            "logs-archive": [],
        }

    def list_buckets(self):
        return list(self.buckets.keys())

    def list_objects(self, bucket):
        return self.buckets.get(bucket, [])

    def download_object(self, bucket, filename, dest):
        Path(dest).mkdir(exist_ok=True)
        filepath = Path(dest) / filename
        with open(filepath, "w") as f:
            f.write(json.dumps({"synthetic": True, "file": filename}))
        return filepath


# -------------------------------------------------------------------
# Cloud Pivot & Exfiltration Simulation
# -------------------------------------------------------------------

def run():
    """
        This module harvests cloud credentials to access the AWS environment 
        and exfiltrate simulated customer PII data from S3 storage, 
        replicating the Scattered Spider data theft model.

        Steps:
        1. Authenticate to AWS using IAM credentials found in previous steps
        2. Create IAM backdoor user 
        3. Enumerate S3 buckets 
        4. Identify the customer database bucket 
        5. Exfiltrate its data 
        6. Produce extortion note

        Creates an extortion note and exports the AWS data.

    """

    iam = MockIAM()
    s3 = MockS3()

    logger.info("Phase 6: Cloud Pivot & Data Exfiltration Simulation ")

    # 1. Authenticate using harvested credentials
    logger.info("Authenticating with harvested credentials...")
    if iam.authenticate("SIMCORPUSER123"):
        logger.info("Authentication successful")
    else:
        logger.error("Authentication failed")
        return

    # 2. Create backdoor IAM user
    backdoor_user = iam.create_user("backup_admin")

    # 3. Enumerate S3 buckets
    logger.info("Enumerating S3 buckets...")
    buckets = s3.list_buckets()
    logger.info(f"Buckets discovered: {buckets}")

    # 4. Identify bucket containing synthetic PII
    pii_bucket = None
    for bucket in buckets:
        objects = s3.list_objects(bucket)
        if objects:
            pii_bucket = bucket
            logger.info(f"Identified PII bucket: {pii_bucket}")
            break

    if not pii_bucket:
        logger.warning("No PII bucket found")
        return

    # 5. Exfiltrate data
    logger.info("Downloading synthetic PII data...")
    exfil_start = datetime.now()
    downloaded_files = []

    for obj in s3.list_objects(pii_bucket):
        file_path = s3.download_object(pii_bucket, obj["filename"], dest=EXFIL_DATA_DIR)
        downloaded_files.append(file_path)
        logger.info(f"Downloaded {obj['filename']} ({obj['size_kb']} KB)")

    exfil_end = datetime.now()

    # Logging operations
    logger.info("Exfiltration Summary")
    logger.info(f"Start: {exfil_start}")
    logger.info(f"End:   {exfil_end}")
    logger.info(f"Files exfiltrated: {len(downloaded_files)}")

    # 6. Generate extortion note
    note = f"""
    Synthetic customer data has been extracted from bucket: {pii_bucket}
    Files:
    {', '.join([f.name for f in downloaded_files])}
    """

    with open(f"{OUTPUT_DIR}/extortion_note.txt", "w") as f:
        f.write(note)

    logger.info("Generated simulated extortion note: extortion_note.txt")
    logger.info("=== Simulation Complete ===")


if __name__ == "__main__":
    run()