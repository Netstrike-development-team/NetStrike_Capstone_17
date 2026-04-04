#!/usr/bin/env python3
"""
Module 07: Ransomware Simulation
Replicates Scattered Spider/RansomHub ransomware deployment across ESXi vCenter infrastructure.

Can be used in two modes:
1. Orchestrator mode: run(config) -> list[dict] for NetStrike framework
2. Standalone mode: python main.py --standalone to encrypt fake files locally for testing
"""

import os
import sys
import json
import uuid
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any
import argparse
import yaml

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)


# ============================================================================
# ORCHESTRATOR MODE: vCenter-based ransomware simulation
# ============================================================================

def run(config: dict) -> List[Dict[str, Any]]:
    """
    Execute RansomHub-style ransomware simulation against ESXi VMs.
    
    Args:
        config: Dictionary with keys:
            - vcenter: {host, username, password}
            - target_vms: List of VM names
            - ransom: {amount, attacker_email}
    
    Returns:
        list[dict]: 5 events matching schemas/event.json
    """
    events = []
    
    # Phase 1: vCenter authentication
    vcenter_config = config.get("vcenter", {})
    if vcenter_authenticate(vcenter_config):
        events.append(emit_event(
            phase=7,
            technique_id="T1469",
            tactic="initial-access",
            description="Accessed vCenter with domain credentials",
            raw_data={"vcenter_host": vcenter_config.get("host")}
        ))
    else:
        return [error_event("vCenter authentication failed")]
    
    # Phase 2: VM enumeration
    vms = vcenter_list_vms(config.get("target_vms", []))
    events.append(emit_event(
        phase=7,
        technique_id="T1526",
        tactic="reconnaissance",
        description=f"Enumerated {len(vms)} virtual machines",
        raw_data={"vm_count": len(vms), "vms": [vm["name"] for vm in vms]}
    ))
    
    # Phase 3: Disable backups/VSS
    for vm in vms:
        simulate_vss_deletion(vm)
        simulate_backup_disable(vm)
    
    events.append(emit_event(
        phase=7,
        technique_id="T1490",
        tactic="defense-evasion",
        description="Disabled VSS shadow copies and backup services",
        raw_data={"vms_affected": len(vms)}
    ))
    
    # Phase 4: Encrypt .vmdk files (create markers)
    encrypted_files = 0
    for vm in vms:
        for vmdk_file in find_vmdk_files(vm):
            create_encryption_marker(vmdk_file)
            encrypted_files += 1
    
    events.append(emit_event(
        phase=7,
        technique_id="T1486",
        tactic="impact",
        description=f"Encrypted {encrypted_files} virtual machine images",
        raw_data={
            "files_encrypted": encrypted_files,
            "vms": [vm["name"] for vm in vms]
        }
    ))
    
    # Phase 5: Deploy ransom notes (Flag 7)
    ransom_config = config.get("ransom", {})
    ransom_count = 0
    for vm in vms:
        if write_ransom_note(vm, ransom_config):
            ransom_count += 1
    
    ransom_amount = ransom_config.get("amount", "$500,000")
    attacker_email = ransom_config.get("attacker_email", "contact@ransomhub.local")
    
    events.append(emit_event(
        phase=7,
        technique_id="T1486",
        tactic="impact",
        description="Ransomware payload deployed - Full attack chain executed successfully",
        flag_triggered="Flag 7 - Ransomware Deployed: Attacker has encrypted VM images and deployed ransom notes across ESXi infrastructure",
        raw_data={
            "ransom_notes_deployed": ransom_count,
            "vms_targeted": [vm["name"] for vm in vms],
            "ransom_amount": ransom_amount,
            "attacker_contact": attacker_email
        }
    ))
    
    vcenter_disconnect()
    return events


# ============================================================================
# STANDALONE MODE: Local file encryption for testing/demonstration
# ============================================================================

def run_standalone(test_dir: str = None) -> List[Dict[str, Any]]:
    """
    Standalone mode: Create and encrypt fake files locally for testing.
    
    Args:
        test_dir: Directory to create fake files. If None, uses ./ransomware_test_files/
    
    Returns:
        list[dict]: 5 events from the simulated attack
    """
    if test_dir is None:
        test_dir = "./ransomware_test_files"
    
    test_dir = Path(test_dir)
    
    # Create test directory
    test_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"[STANDALONE] Created test directory: {test_dir.absolute()}")
    
    events = []
    
    # Phase 1: vCenter authentication (simulated)
    events.append(emit_event(
        phase=7,
        technique_id="T1469",
        tactic="initial-access",
        description="[STANDALONE] Simulated vCenter authentication",
        raw_data={"target": "localhost"}
    ))
    
    # Phase 2: File enumeration (reconnaissance)
    fake_files = create_fake_files(test_dir)
    events.append(emit_event(
        phase=7,
        technique_id="T1526",
        tactic="reconnaissance",
        description=f"Enumerated {len(fake_files)} files for encryption",
        raw_data={"file_count": len(fake_files), "files": fake_files}
    ))
    
    # Phase 3: Disable backups/VSS (simulated)
    events.append(emit_event(
        phase=7,
        technique_id="T1490",
        tactic="defense-evasion",
        description="[STANDALONE] Simulated disabling of system backups",
        raw_data={"backups_disabled": True}
    ))
    
    # Phase 4: Encrypt files (create .RANSOMHUB markers)
    encrypted_files = encrypt_files_locally(test_dir, fake_files)
    events.append(emit_event(
        phase=7,
        technique_id="T1486",
        tactic="impact",
        description=f"Encrypted {encrypted_files} files locally",
        raw_data={
            "files_encrypted": encrypted_files,
            "location": str(test_dir.absolute())
        }
    ))
    
    # Phase 5: Deploy ransom notes (Flag 7)
    ransom_note_path = deploy_ransom_note_standalone(test_dir)
    events.append(emit_event(
        phase=7,
        technique_id="T1486",
        tactic="impact",
        description="Ransomware payload deployed - Ransom note written to target directory",
        flag_triggered="Flag 7 - Ransomware Deployed: Attacker has encrypted files and deployed ransom notes",
        raw_data={
            "ransom_note_location": str(ransom_note_path.absolute()),
            "files_encrypted": encrypted_files,
            "target_directory": str(test_dir.absolute())
        }
    ))
    
    logger.info(f"[STANDALONE] Ransomware simulation complete. Test files in: {test_dir.absolute()}")
    logger.info(f"[STANDALONE] View ransom note: {ransom_note_path}")
    
    return events


def create_fake_files(target_dir: Path, count: int = 5) -> List[str]:
    """Create fake files with extensions matching ransom targets."""
    extensions = [".docx", ".xlsx", ".pdf", ".json", ".txt"]
    fake_files = []
    
    for i, ext in enumerate(extensions[:count]):
        filename = f"important_file_{i+1}{ext}"
        filepath = target_dir / filename
        
        # Create fake content
        content = f"Sensitive data file {i+1}\nThis would be encrypted by ransomware.\n" * 100
        filepath.write_text(content)
        fake_files.append(filename)
        logger.info(f"[STANDALONE] Created fake file: {filename}")
    
    return fake_files


def encrypt_files_locally(target_dir: Path, fake_files: List[str]) -> int:
    """Create encryption markers for fake files."""
    encrypted_count = 0
    
    for filename in fake_files:
        filepath = target_dir / filename
        marker_path = filepath.with_suffix(filepath.suffix + ".RANSOMHUB")
        
        # Create marker file
        marker_content = f"This file has been encrypted by RANSOMHUB\nOriginal: {filename}\n"
        marker_path.write_text(marker_content)
        
        # Optionally "encrypt" the original by appending marker
        if filepath.exists():
            with open(filepath, "a") as f:
                f.write("\n\n[ENCRYPTED BY RANSOMHUB - ORIGINAL DATA REMAINS FOR DEMO]")
        
        encrypted_count += 1
        logger.info(f"[STANDALONE] Marked file as encrypted: {filename}")
    
    return encrypted_count


def deploy_ransom_note_standalone(target_dir: Path) -> Path:
    """Write ransom note to standalone test directory."""
    ransom_note_content = """

╔════════════════════════════════════════════════════════════════╗
║                                                                ║
║                 ⚠️  YOUR FILES ARE ENCRYPTED  ⚠️              ║
║                                                                ║
║                      RANSOMHUB RANSOMWARE                      ║
║                                                                ║
╚════════════════════════════════════════════════════════════════╝

Your infrastructure has been encrypted and is no longer accessible.
All your sensitive files, databases, and backups have been stolen.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

WHAT HAPPENED?

Your systems were compromised due to weak security practices:
- Unpatched remote access vulnerabilities
- Stolen domain admin credentials
- Lack of network segmentation
- No multi-factor authentication

All your data has been exfiltrated to our secure servers.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

RANSOM DEMAND

Provide $500000 USD in Bitcoin to recover your files.

Payment Address: 1RansomHub123456789ABCDEFGHIJKLMN
Payment Deadline: 7 days from now

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

HOW TO CONTACT US

Email: contact@ransomhub.local
Onion Address: ransomhub.onion

Include your unique case ID in all communications:
CASE-ID-SIM-20260404175016

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

DO NOT:
❌ Try to recover files yourself (will corrupt them)
❌ Contact law enforcement (will result in data release)
❌ Shut down systems (will complicate recovery)

DO:
✅ Contact us immediately with your case ID
✅ Be prepared to negotiate
✅ Respond within 7 days

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Time is running out. Act now.

[This is a SIMULATED ransom note for educational purposes]
"""
    
    ransom_note_file = target_dir / "README_RANSOMHUB.txt"
    ransom_note_file.write_text(ransom_note_content, encoding='utf-8')
    logger.info(f"[STANDALONE] Deployed ransom note to {ransom_note_file.name}")
    
    return ransom_note_file


# ============================================================================
# HELPER FUNCTIONS: vCenter simulation
# ============================================================================

def vcenter_authenticate(vcenter_config: dict) -> bool:
    """Simulate vCenter authentication."""
    host = vcenter_config.get("host", "unknown")
    username = vcenter_config.get("username", "unknown")
    logger.info(f"[SIM] Authenticating to {host} as {username}")
    return True


def vcenter_list_vms(target_vms: List[str]) -> List[Dict[str, str]]:
    """Return list of target VMs configured."""
    if not target_vms:
        target_vms = ["CITEF-VM-01", "CITEF-VM-02", "DB-Server"]
    
    vms = []
    for vm_name in target_vms:
        vms.append({
            "name": vm_name,
            "vmdk_path": f"[datastore1] {vm_name}/"
        })
    return vms


def find_vmdk_files(vm: dict) -> List[str]:
    """Find .vmdk files in VM directory."""
    return [
        f"{vm['vmdk_path']}{vm['name']}.vmdk",
        f"{vm['vmdk_path']}{vm['name']}_backup.vmdk"
    ]


def create_encryption_marker(file_path: str) -> None:
    """Create .RANSOMHUB marker file."""
    marker_path = file_path + ".RANSOMHUB"
    logger.info(f"[SIM] Marked file as encrypted: {marker_path}")


def simulate_vss_deletion(vm: dict) -> None:
    """Log VSS deletion command."""
    logger.info(f"[SIM] Deleted VSS shadow copies on {vm['name']}")


def simulate_backup_disable(vm: dict) -> None:
    """Log backup service disable."""
    logger.info(f"[SIM] Disabled backup jobs on {vm['name']}")


def write_ransom_note(vm: dict, ransom_config: dict) -> bool:
    """Write RansomHub-style ransom note."""
    note_path = f"/tmp/{vm['name']}/README_RANSOMHUB.txt"
    logger.info(f"[SIM] Deployed ransom note to {note_path}")
    return True


def vcenter_disconnect() -> None:
    """Disconnect from vCenter."""
    logger.info("[SIM] Disconnected from vCenter")


# ============================================================================
# EVENT GENERATION
# ============================================================================

def emit_event(phase: int, technique_id: str, tactic: str, description: str,
               flag_triggered: str = None, raw_data: dict = None) -> Dict[str, Any]:
    """Generate a single event."""
    return {
        "event_id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        "phase": phase,
        "technique_id": technique_id,
        "tactic": tactic,
        "description": description,
        "source_module": "07-ransomware-sim",
        "flag_triggered": flag_triggered,
        "raw_data": raw_data or {}
    }


def error_event(message: str) -> Dict[str, Any]:
    """Generate an error event."""
    return {
        "event_id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        "phase": 0,
        "technique_id": "UNKNOWN",
        "tactic": "error",
        "description": f"Ransomware simulation error: {message}",
        "source_module": "07-ransomware-sim",
        "flag_triggered": None,
        "raw_data": {"error": message}
    }


# ============================================================================
# ENTRYPOINT
# ============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Module 07: Ransomware Simulation (vCenter or standalone mode)"
    )
    parser.add_argument(
        "--standalone",
        action="store_true",
        help="Run in standalone mode (create and encrypt fake files locally)"
    )
    parser.add_argument(
        "--test-dir",
        type=str,
        default="./ransomware_test_files",
        help="Directory for test files in standalone mode (default: ./ransomware_test_files)"
    )
    parser.add_argument(
        "--config",
        type=str,
        default="config.yaml",
        help="Path to YAML config file for orchestrator mode (default: config.yaml)"
    )
    
    args = parser.parse_args()
    
    try:
        if args.standalone:
            # Standalone mode: encrypt fake files locally
            logger.info("=" * 70)
            logger.info("RANSOMWARE SIMULATION - STANDALONE MODE")
            logger.info("=" * 70)
            events = run_standalone(args.test_dir)
            
            # Print results
            logger.info("\n" + "=" * 70)
            logger.info("EVENTS GENERATED:")
            logger.info("=" * 70)
            for i, event in enumerate(events, 1):
                logger.info(f"\nEvent {i}: {event['technique_id']} - {event['description']}")
                if event.get("flag_triggered"):
                    logger.info(f"  ⚠️  FLAG: {event['flag_triggered']}")
            
            # Output as JSON
            print("\n\nJSON Output:")
            print(json.dumps(events, indent=2))
        
        else:
            # Orchestrator mode: read config and run
            logger.info("=" * 70)
            logger.info("RANSOMWARE SIMULATION - ORCHESTRATOR MODE")
            logger.info("=" * 70)
            
            if not os.path.exists(args.config):
                logger.error(f"Config file not found: {args.config}")
                sys.exit(1)
            
            with open(args.config, 'r') as f:
                config = yaml.safe_load(f)
            
            events = run(config)
            
            # Print results
            logger.info("\n" + "=" * 70)
            logger.info("EVENTS GENERATED:")
            logger.info("=" * 70)
            for i, event in enumerate(events, 1):
                logger.info(f"\nEvent {i}: {event['technique_id']} - {event['description']}")
                if event.get("flag_triggered"):
                    logger.info(f"  ⚠️  FLAG: {event['flag_triggered']}")
            
            # Output as JSON
            print("\n\nJSON Output:")
            print(json.dumps(events, indent=2))
    
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        sys.exit(1)
