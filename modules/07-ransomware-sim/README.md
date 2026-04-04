# Module 07 - Ransomware Simulation

Ransomware simulation module for ESXi vCenter infrastructure attacks.

## Overview

This module replicates the Scattered Spider/RansomHub ransomware attack chain targeting VMware infrastructure. It demonstrates a realistic 5-phase attack:

1. **T1469** — Initial Access (vCenter Authentication)
2. **T1526** — Reconnaissance (VM Enumeration)
3. **T1490** — Defense Evasion (Disable VSS/Backups)
4. **T1486** — Impact (Encrypt Files)
5. **T1486** — Impact (Deploy Ransom Notes + Flag 7)

**Execution Time**: ~100ms  
**Events Generated**: 5 (one per phase)  
**Dependencies**: pyyaml

---

## Quick Start

### Orchestrator Mode (vCenter)

```python
from main import run

config = {
    "vcenter": {
        "host": "vcenter.citef.local",
        "username": "domain_admin",
        "password": "REDACTED"
    },
    "target_vms": ["CITEF-VM-01", "CITEF-VM-02"],
    "ransom": {
        "amount": "$500,000",
        "attacker_email": "contact@ransomhub.local"
    }
}

events = run(config)
print(f"Generated {len(events)} events")
for event in events:
    print(f"  {event['technique_id']}: {event['description']}")
```

### Standalone Mode (Encrypt Local Files)

```bash
# Create fake files on your machine and encrypt them
python main.py --standalone

# View results
ls ./ransomware_test_files/
cat ./ransomware_test_files/README_RANSOMHUB.txt
```

---

## File Structure

```
modules/07-ransomware-sim/
├── main.py                  # run() + run_standalone()
├── config.yaml             # Configuration
├── requirements.txt        # pyyaml
├── README.md              # This file
└── tests/
    └── test_main.py       # Unit tests
```

---

## Configuration

Configuration file (config.yaml):

```yaml
# config.yaml

vcenter:
  host: vcenter.citef.local
  username: domain_admin
  password: REDACTED_FOR_SECURITY
  port: 443

target_vms:
  - CITEF-VM-01
  - CITEF-VM-02
  - DB-Server

ransom:
  amount: "$500,000"
  currency: "Bitcoin"
  attacker_email: contact@ransomhub.local
  deadline_days: 7

file_extensions:
  - .vmdk
  - .docx
  - .xlsx
  - .pdf
  - .db

simulation_mode: true
logging:
  level: INFO
```

---

## Usage

### As Orchestrator Module

```python
# Called by NetStrike orchestrator
from main import run
import yaml

with open('config.yaml') as f:
    config = yaml.safe_load(f)

events = run(config)  # Returns list[dict]
```

### Standalone (Local Testing)

```bash
# Run with default settings (creates ./ransomware_test_files/)
python main.py --standalone

# Custom test directory
python main.py --standalone --test-dir /tmp/ransomware_demo
```

### With Custom Config

```bash
# Orchestrator mode using custom config
python main.py --config ./config-custom.yaml
```

---

## Return Value

Both modes return 5 events conforming to `schemas/event.json`:

```json
[
  {
    "event_id": "uuid-1",
    "timestamp": "2026-04-04T14:32:01Z",
    "phase": 7,
    "technique_id": "T1469",
    "tactic": "initial-access",
    "description": "Accessed vCenter with domain credentials",
    "source_module": "07-ransomware-sim",
    "flag_triggered": null,
    "raw_data": {"vcenter_host": "vcenter.citef.local"}
  },
  {
    "event_id": "uuid-2",
    "timestamp": "2026-04-04T14:32:02Z",
    "phase": 7,
    "technique_id": "T1526",
    "tactic": "reconnaissance",
    "description": "Enumerated 3 virtual machines",
    "source_module": "07-ransomware-sim",
    "flag_triggered": null,
    "raw_data": {"vm_count": 3, "vms": ["CITEF-VM-01", "CITEF-VM-02", "DB-Server"]}
  },
  {
    "event_id": "uuid-3",
    "timestamp": "2026-04-04T14:32:03Z",
    "phase": 7,
    "technique_id": "T1490",
    "tactic": "defense-evasion",
    "description": "Disabled VSS shadow copies and backup services",
    "source_module": "07-ransomware-sim",
    "flag_triggered": null,
    "raw_data": {"vms_affected": 3}
  },
  {
    "event_id": "uuid-4",
    "timestamp": "2026-04-04T14:32:04Z",
    "phase": 7,
    "technique_id": "T1486",
    "tactic": "impact",
    "description": "Encrypted 6 virtual machine images",
    "source_module": "07-ransomware-sim",
    "flag_triggered": null,
    "raw_data": {"files_encrypted": 6, "vms": ["CITEF-VM-01", "CITEF-VM-02", "DB-Server"]}
  },
  {
    "event_id": "uuid-5",
    "timestamp": "2026-04-04T14:32:05Z",
    "phase": 7,
    "technique_id": "T1486",
    "tactic": "impact",
    "description": "Ransomware payload deployed - Full attack chain executed successfully",
    "source_module": "07-ransomware-sim",
    "flag_triggered": "Flag 7 - Ransomware Deployed: Attacker has encrypted VM images and deployed ransom notes across ESXi infrastructure",
    "raw_data": {
      "ransom_notes_deployed": 3,
      "vms_targeted": ["CITEF-VM-01", "CITEF-VM-02", "DB-Server"],
      "ransom_amount": "$500,000",
      "attacker_contact": "contact@ransomhub.local"
    }
  }
]
```

## Standalone Mode - Local Files

When run with `--standalone`, the module:

1. **Creates** 5 fake files (important_file_1.docx through .txt)
2. **Encrypts** them by creating .RANSOMHUB markers
3. **Deploys** ransom note (README_RANSOMHUB.txt)
4. **Emits** the same 5 events (for demonstration)

```
$ python main.py --standalone
[INFO] RANSOMWARE SIMULATION - STANDALONE MODE
[INFO] [STANDALONE] Created test directory: /current/dir/ransomware_test_files
[INFO] [STANDALONE] Created fake file: important_file_1.docx
[INFO] [STANDALONE] Created fake file: important_file_2.xlsx
...
[INFO] [STANDALONE] Marked file as encrypted: important_file_1.docx
[INFO] [STANDALONE] Marked file as encrypted: important_file_1.xlsx
...
[INFO] [STANDALONE] Deployed ransom note to README_RANSOMHUB.txt

$ ls ransomware_test_files/
important_file_1.docx
important_file_1.docx.RANSOMHUB
important_file_2.xlsx
important_file_2.xlsx.RANSOMHUB
...
README_RANSOMHUB.txt
```

---

## Testing

```bash
# Install dependencies
pip install -r requirements.txt

# Run all tests
python -m pytest tests/test_main.py -v

# Test orchestrator mode
python -c "
from main import run
config = {'vcenter': {'host': 'test.local'}, 'target_vms': ['VM1'], 'ransom': {'amount': '\$100k'}}
events = run(config)
assert len(events) == 5
print('✓ Orchestrator mode works')
"

# Test standalone mode
python -c "
import shutil
from pathlib import Path
from main import run_standalone
test_dir = './test_run'
events = run_standalone(test_dir)
assert len(events) == 5
assert Path(test_dir).exists()
shutil.rmtree(test_dir)
print('✓ Standalone mode works')
"
```

---

## API Reference

### `run(config: dict) -> list[dict]`

Execute RansomHub-style ransomware simulation against vCenter VMs.

**Parameters:**
- `config` — Dict with keys: `vcenter`, `target_vms`, `ransom`

**Returns:**
- `list[dict]` — 5 events conforming to schemas/event.json

**Example:**
```python
events = run({
    "vcenter": {"host": "vcenter.local", "username": "admin"},
    "target_vms": ["VM-01"],
    "ransom": {"amount": "$500k", "attacker_email": "attacker@example.com"}
})
```

### `run_standalone(test_dir: str = None) -> list[dict]`

Create and encrypt fake files locally for testing/demonstration.

**Parameters:**
- `test_dir` — Directory for test files (default: `./ransomware_test_files`)

**Returns:**
- `list[dict]` — 5 events from simulated attack

**Example:**
```python
events = run_standalone("./my_test_dir")
# Creates files in ./my_test_dir and .RANSOMHUB markers
```

---

## MITRE ATT&CK Coverage

| Technique | Tactic | Description |
|-----------|--------|-------------|
| T1469 | Initial Access | vCenter authentication |
| T1526 | Reconnaissance | VM enumeration |
| T1490 | Defense Evasion | VSS/backup disabling |
| T1486 | Impact | File encryption + ransom notes |

---

## Requirements

```
pyyaml
```

No other dependencies. Install with:

```bash
pip install -r requirements.txt
```

---

## Notes

- **Simulation Only**: All operations are logged; no real files are encrypted
- **Marker Files**: Uses `.RANSOMHUB` extension to indicate encrypted files
- **Fast**: Completes in ~100ms with minimal overhead
- **Testable**: Both `run()` and `run_standalone()` can be tested independently

---

**Module Version**: 2.0  
**Last Updated**: April 4, 2026
