# Module 07 - Ransomware Simulation

Ransomware simulation module for ESXi vCenter infrastructure attacks, replicating the Scattered Spider/RansomHub attack chain.

## Overview

This module demonstrates a realistic 5-phase ransomware attack targeting VMware infrastructure:

1. **T1469** — Initial Access (vCenter Authentication with stolen credentials)
2. **T1526** — Reconnaissance (Virtual Machine Enumeration)
3. **T1490** — Defense Evasion (Disable VSS Shadow Copies & Backup Services)
4. **T1486** — Impact (Encrypt Virtual Machine Disk Images)
5. **T1486** — Impact (Deploy Ransom Notes + Trigger Flag 7)

**Execution Time**: ~100ms  
**Events Generated**: 5 (one per phase)  
**Dependencies**: PyYAML, pycryptodome  
**Module Version**: 2.0  
**Last Updated**: April 4, 2026

---

## File Structure

```
modules/07-ransomware-sim/
├── main.py                     # Orchestrator and standalone mode execution
├── encryption.py               # AES-256 encryption/decryption utilities
├── config.yaml                 # Configuration for vCenter and encryption
├── requirements.txt            # Python dependencies (PyYAML, pycryptodome)
├── OVERVIEW.md                 # This file (architecture & reference)
├── USAGE.md                    # Usage guide (configuration & examples)
└── tests/
    └── test_main.py            # Unit tests
```

---

## Attack Chain Architecture

### Phase 1: Initial Access (T1469)

Authenticate to vCenter infrastructure using stolen domain admin credentials.

```
Attacker →[stolen creds]→ vCenter API → Success/Failure event
```

**Event Generated:**
- Technique: T1469
- Description: "Accessed vCenter with domain credentials"
- Data: vCenter host and authentication result

### Phase 2: Reconnaissance (T1526)

Enumerate all virtual machines in vCenter to identify targets.

```
vCenter → VM List → [Count & Names] → Reconnaissance event
```

**Event Generated:**
- Technique: T1526
- Description: "Enumerated X virtual machines"
- Data: VM count, VM names, vCenter infrastructure topology

### Phase 3: Defense Evasion (T1490)

Disable backup systems and VSS (Volume Shadow Copy Service) to prevent recovery.

```
For each VM:
  ├─ Delete VSS shadow copies
  └─ Disable backup services
```

**Event Generated:**
- Technique: T1490
- Description: "Disabled VSS shadow copies and backup services"
- Data: Number of affected VMs

### Phase 4: Encryption (T1486)

Encrypt VMDK (virtual machine disk) files using marker mode or AES-256.

```
For each VM's VMDK:
  ├─ [Marker Mode] Create .RANSOMHUB marker file
  └─ [Safe Mode] Copy & encrypt with AES-256
```

**Event Generated:**
- Technique: T1486
- Description: "Encrypted X virtual machine images"
- Data: File count, VM names, encryption mode used

### Phase 5: Ransom Deployment (T1486 + Flag 7)

Deploy threatening ransom notes and trigger the Flag 7 defense condition.

```
For each VM directory:
  └─ Write README_RANSOMHUB.txt with ransom demands
  
├─ Flag 7 Triggered: "Ransomware Deployed"
└─ Attacker contact info & payment demands
```

**Event Generated:**
- Technique: T1486
- Description: "Ransomware payload deployed - Full attack chain executed"
- flag_triggered: **Flag 7 - Ransomware Deployed**
- Data: Ransom notes deployed, target VMs, ransom amount, attacker email

---

## Execution Modes

### Orchestrator Mode

Called by the NetStrike framework to generate events from a vCenter configuration.

```python
from main import run

config = {
    "vcenter": {"host": "vcenter.local", "username": "admin", "password": "***"},
    "target_vms": ["VM-01", "VM-02"],
    "ransom": {"amount": "$500k", "attacker_email": "attacker@example.com"}
}

events = run(config)  # Returns 5 events
```

- **Input**: Configuration dict with vCenter credentials and target VMs
- **Output**: List of 5 events conforming to `schemas/event.json`
- **Use Case**: Integration with NetStrike orchestrator, SIEM testing

### Standalone Mode

Local testing mode that creates fake files and encrypts them without vCenter access.

```bash
python main.py --standalone
```

- **Input**: Optional test directory path
- **Output**: 5 simulated events + encrypted files on disk
- **Use Case**: Testing encryption locally, demonstration, lab environment

Both modes return the same event structure and flow through all 5 attack phases.

---

## Event Output Format

All events conform to `schemas/event.json` with the following structure:

```json
{
  "event_id": "uuid-123",
  "timestamp": "2026-04-04T14:32:01Z",
  "phase": 7,
  "technique_id": "T1486",
  "tactic": "impact",
  "description": "Encrypted X files",
  "source_module": "07-ransomware-sim",
  "flag_triggered": "Flag 7 - Ransomware Deployed: ...",
  "raw_data": {
    "files_encrypted": 6,
    "vms": ["VM-01", "VM-02"]
  }
}
```

---

## Encryption Modes

The module supports **two encryption modes** for standalone testing:

### Marker Mode (Default)
- **Non-destructive**: Creates `.RANSOMHUB` marker files
- **Original files**: Remain unchanged
- **Performance**: Fast (no actual encryption)
- **Best for**: Quick demonstrations, initial testing
- **Security**: Simulates encryption effect without computational cost

### Safe Mode (AES-256)
- **Non-destructive**: Copies files before encrypting
- **Encryption**: Real AES-256-CBC encryption
- **Reversible**: Easily decrypt with the same key
- **Performance**: Slower (crypto overhead)
- **Best for**: Realistic testing, SIEM log validation, demonstration

**Safe Mode Technical Details:**
- Algorithm: AES-256-CBC (256-bit key)
- IV: Per-file random 16-byte IV stored with ciphertext
- Format: `[IV (16 bytes)][Encrypted Data]`
- Key: Static, configurable hex string (32 characters)
- Recovery: Single command with the same key

---

## MITRE ATT&CK Coverage

| Technique ID | Technique Name | Tactic | Description |
|---|---|---|---|
| T1469 | Obtain Capabilities | Initial Access | vCenter authentication with stolen credentials |
| T1526 | Gather Victim Org Information | Reconnaissance | Enumerate virtual machines |
| T1490 | Inhibit System Recovery | Defense Evasion | Disable VSS and backup services |
| T1486 | Data Encrypted for Impact | Impact | Encrypt VMDK files and deploy ransom notes |

---

## Real-World Attack Context

### Scattered Spider / UNC3944

Scattered Spider is known for:
- Targeting large enterprises with complex infrastructure
- Using social engineering to obtain domain credentials
- Disabling backups and recovery systems
- Deploying RansomHub ransomware

### Attack Progression

1. **Initial Access** (Weeks 1-2): Obtain VPN/RDP access via phishing
2. **Lateral Movement** (Weeks 2-4): Move to domain controller, obtain domain admin
3. **Reconnaissance** (Day of attack): Map infrastructure, identify critical VMs
4. **Disable Defenses** (Day of attack, Hour 1): Delete backups, disable VSS
5. **Encrypt & Extort** (Day of attack, Hour 2): Encrypt VMs, deploy ransom notes

This module simulates **Phases 2-5** of the attack chain.

---

## Technical Implementation

### vCenter Simulation

In orchestrator mode, the module:
1. Simulates vCenter API authentication
2. Returns simulated VM lists
3. Logs operations as if connected to real vCenter
4. Does not require real vCenter access for testing

### Extensibility

The module is designed to be extended:
- Replace `vcenter_authenticate()` with real pyVmomi calls
- Replace `vcenter_list_vms()` with real VM enumeration
- Replace encryption markers with actual VMDK encryption
- Replace ransom note creation with multi-VM deployment

---

## Security Considerations

⚠️ **This is an educational simulation for authorized testing only.**

- **Marker Mode**: No real encryption, safe for any environment
- **Safe Mode**: Real AES-256 encryption (easily reversible with key)
- **No Network Access**: Does not connect to real systems by default
- **No Destructive Changes**: Original files are never harmed in either mode

### For Legitimate Testing

- Run in isolated lab environments
- Use safe mode for realistic encryption validation
- Keep encryption keys secure if using real data
- Monitor SIEM/detection systems during runs
- Document authorization before testing

---

## Design Philosophy

This module balances:

- **Realism**: Accurate simulation of actual attack chain and techniques
- **Safety**: Non-destructive, reversible operations
- **Flexibility**: Supports both simulation and real integration
- **Testability**: Can be unit tested without external dependencies
- **Clarity**: Well-documented code with clear separation of concerns

---

## Module Dependencies

```
PyYAML          - YAML configuration parsing
pycryptodome    - AES-256 encryption (safe mode only, safe mode optional)
```

No pyVmomi or vCenter dependencies required for standalone mode.

---

## Return to USAGE.md

For configuration, running the module, and detailed examples, see [USAGE.md](USAGE.md).
