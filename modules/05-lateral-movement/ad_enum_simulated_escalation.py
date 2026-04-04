"""
Active Directory Enumeration

MITRE ATT&CK :
    T1069 : Permission Groups Discovery (reviewing AD group structure)
    T1087 : Account Discovery (auditing domain user accounts)
"""


import os
import sys
import csv
import logging
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
import getpass

# ---------------------------------------------------------------------------
# Output folder structure
# ---------------------------------------------------------------------------

OUTPUT_DIR = Path("output")
LOG_DIR = OUTPUT_DIR / "logs"
AUDIT_DIR = OUTPUT_DIR / "audits"

LOG_DIR.mkdir(parents=True, exist_ok=True)
AUDIT_DIR.mkdir(parents=True, exist_ok=True)

LOG_FILE = LOG_DIR / "ad_audit.log"

# ---------------------------------------------------------------------------
# Logging setup (console + file)
# ---------------------------------------------------------------------------

logger = logging.getLogger("ad-audit")
logger.setLevel(logging.INFO)

formatter = logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

# Console handler
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# File handler
file_handler = logging.FileHandler(LOG_FILE)
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

logger.info("Logger initialized.")

# ---------------------------------------------------------------------------
# Ensure ldap3 is installed
# ---------------------------------------------------------------------------

try:
    from ldap3 import Server, Connection, ALL, SUBTREE
except ImportError:
    logger.warning("ldap3 not found, installing...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "ldap3"])
        from ldap3 import Server, Connection, ALL, SUBTREE
        logger.info("ldap3 installed successfully.")
    except Exception as e:
        logger.error(f"Failed to install ldap3: {e}")
        sys.exit(1)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DOMAIN = os.environ.get("USERDOMAIN")
USERNAME = os.environ.get("USERNAME")

AD_USER = f"{DOMAIN}\\{USERNAME}"

AD_SERVER = "ldap://simcorp.com"
BASE_DN = "DC=simcorp,DC=com"

# The password is discovered in the previous steps, osint-profiler
AD_PASSWORD = getpass.getpass(f"Enter password for {AD_USER}: ") 

CURRENT_STAGE = "STANDARD_USER"


STALE_DAYS = 90

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def filetime_to_datetime(filetime):
    try:
        ft = int(filetime)
        if ft == 0:
            return None
        return datetime(1601, 1, 1) + timedelta(microseconds=ft / 10)
    except Exception:
        return None

def has_flag(uac, flag):
    try:
        return (int(uac) & flag) == flag
    except Exception:
        return False

UAC_DISABLED = 0x0002
UAC_PWD_NOT_REQUIRED = 0x0020
UAC_PWD_NEVER_EXPIRES = 0x10000
UAC_SMARTCARD_REQUIRED = 0x40000

# ---------------------------------------------------------------------------
# Safe LDAP search wrapper
# ---------------------------------------------------------------------------

def safe_search(conn, base, filter, attrs):
    try:
        conn.search(base, filter, SUBTREE, attributes=attrs)
        return conn.entries
    except Exception as e:
        logger.error(f"LDAP search failed ({filter}): {e}")
        return []

# ---------------------------------------------------------------------------
# Connect to AD
# ---------------------------------------------------------------------------

def connect():
    logger.info(f"Connecting to {AD_SERVER} as {AD_USER}...")
    try:
        server = Server(AD_SERVER, get_info=ALL)
        conn = Connection(server, user=AD_USER, password=AD_PASSWORD, auto_bind=True)
        logger.info("Connection successful.")
        return conn
    except Exception as e:
        logger.error(f"Failed to connect to AD: {e}")
        sys.exit(1)

# ---------------------------------------------------------------------------
# User audit
# ---------------------------------------------------------------------------

def audit_users(conn):
    logger.info("Enumerating users...")

    attributes = [
        "sAMAccountName", "displayName", "userAccountControl",
        "lastLogonTimestamp", "pwdLastSet", "memberOf",
        "whenCreated", "description"
    ]

    entries = safe_search(conn, BASE_DN, "(objectClass=user)", attributes)

    users = []
    now = datetime.utcnow()
    stale_threshold = now - timedelta(days=STALE_DAYS)

    for entry in entries:
        e = entry.entry_attributes_as_dict

        uac = e.get("userAccountControl", [0])[0]
        last_logon = filetime_to_datetime(e.get("lastLogonTimestamp", [0])[0])
        pwd_last_set = filetime_to_datetime(e.get("pwdLastSet", [0])[0])

        users.append({
            "sAMAccountName": e.get("sAMAccountName", [""])[0],
            "displayName": e.get("displayName", [""])[0],
            "disabled": has_flag(uac, UAC_DISABLED),
            "pwd_never_expires": has_flag(uac, UAC_PWD_NEVER_EXPIRES),
            "pwd_not_required": has_flag(uac, UAC_PWD_NOT_REQUIRED),
            "smartcard_required": has_flag(uac, UAC_SMARTCARD_REQUIRED),
            "lastLogonTimestamp": last_logon.isoformat() if last_logon else "",
            "pwdLastSet": pwd_last_set.isoformat() if pwd_last_set else "",
            "stale_account": last_logon and last_logon < stale_threshold,
            "memberOf": ";".join(e.get("memberOf", [])),
            "whenCreated": e.get("whenCreated", [""])[0],
            "description": e.get("description", [""])[0] if e.get("description") else ""
        })

    logger.info(f"Found {len(users)} users.")
    return users

# ---------------------------------------------------------------------------
# Group audit
# ---------------------------------------------------------------------------

def audit_groups(conn):
    logger.info("Enumerating groups...")

    entries = safe_search(conn, BASE_DN, "(objectClass=group)",
                          ["cn", "sAMAccountName", "member", "description"])

    groups = []
    for entry in entries:
        e = entry.entry_attributes_as_dict
        groups.append({
            "cn": e.get("cn", [""])[0],
            "sAMAccountName": e.get("sAMAccountName", [""])[0],
            "member_count": len(e.get("member", [])),
            "description": e.get("description", [""])[0] if e.get("description") else ""
        })

    logger.info(f"Found {len(groups)} groups.")
    return groups

# ---------------------------------------------------------------------------
# Computer audit
# ---------------------------------------------------------------------------

def audit_computers(conn):
    logger.info("Enumerating computers...")

    entries = safe_search(conn, BASE_DN, "(objectClass=computer)",
                          ["cn", "dNSHostName", "operatingSystem",
                           "operatingSystemVersion", "lastLogonTimestamp"])

    computers = []
    for entry in entries:
        e = entry.entry_attributes_as_dict
        last_logon = filetime_to_datetime(e.get("lastLogonTimestamp", [0])[0])
        computers.append({
            "cn": e.get("cn", [""])[0],
            "dNSHostName": e.get("dNSHostName", [""])[0],
            "operatingSystem": e.get("operatingSystem", [""])[0],
            "operatingSystemVersion": e.get("operatingSystemVersion", [""])[0],
            "lastLogonTimestamp": last_logon.isoformat() if last_logon else ""
        })

    logger.info(f"Found {len(computers)} computers.")
    return computers

# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

def export_csv(filename, fieldnames, rows):
    export_path = AUDIT_DIR / filename
    logger.info(f"Writing {export_path}...")

    try:
        with open(export_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

        logger.info(f"{export_path} written successfully.")

    except Exception as e:
        logger.error(f"Failed to write {export_path}: {e}")


#----------------------------------------------------------------------------
# Staged privilege escalation
#----------------------------------------------------------------------------

def simulate_escalation(stage_name, credential):
    global CURRENT_STAGE
    old = CURRENT_STAGE
    CURRENT_STAGE = stage_name
    logger.info(f"Stage escalation: {old} -> {stage_name}")
    logger.info(f"Privilege escalation is simulated using pre-staged credential: {credential}")
    return CURRENT_STAGE



# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run():
    """
    This module enumerates the Active Directory, exports audits,
    and simulates Privilege Escalation

    Steps:
      1. Enumerate Active Directory
      2. Exports findings
      3. Simulate Privilege Escalation

    Returns list of profile dicts (sorted highest attack value first).
    """

    # 1. Enumerating Active Directory
    logger.info("Starting AD audit...")

    conn = connect()

    users = audit_users(conn)
    groups = audit_groups(conn)
    computers = audit_computers(conn)

    # 2. Exporting findings
    export_csv("ad_users_audit.csv", users[0].keys(), users)
    export_csv("ad_groups_audit.csv", groups[0].keys(), groups)
    export_csv("ad_computers_audit.csv", computers[0].keys(), computers)

    logger.info("AD audit complete.")

    # 3. Escalating privileges 
    simulate_escalation("PRIVILEGED_USER", "Simulated escalation using pre-staged credentials")


if __name__ == "__main__":
    run()