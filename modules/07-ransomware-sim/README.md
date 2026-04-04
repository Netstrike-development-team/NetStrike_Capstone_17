# Module 07 - Ransomware Simulation

## What It Does

This module simulates a modern ransomware attack targeting VMware ESXi infrastructure, specifically mimicking the RansomHub threat actor group. It demonstrates the complete attack kill chain:

1. **Initial Access**: Authenticates to VMware vCenter with compromised credentials
2. **Reconnaissance**: Enumerates virtual machines and infrastructure
3. **Defense Evasion**: Disables VSS shadow copies and backup services
4. **Impact**: Simulates encryption of critical files
5. **Extortion**: Generates and deploys ransom notes

### MITRE ATT&CK Coverage
- **T1486**: Data Encrypted for Impact (ESXi ransomware)
- **T1490**: Inhibit System Recovery (VSS/backup deletion)

### Safety & Simulation
⚠️ **THIS IS AN EDUCATIONAL SIMULATION FOR AUTHORIZED CITEF LAB ENVIRONMENTS ONLY**

- **Simulation Mode**: All operations are simulated without actually encrypting real files
- **No Real Damage**: Backup files are not deleted; VSS is not actually disabled
- **Marker Files**: Instead of encryption, `.RANSOMHUB` marker files are created
- **Audit Logging**: All simulated actions are logged for review

**DO NOT** use this code against real systems without explicit authorization.


## How To Run

### Via Orchestrator

The orchestrator calls the module's `run()` function with a configuration dict:

```python
from main import run

config = {
    "vcenter_config": {"host": "vcenter.citef.local", "username": "admin"},
    "target_vms": ["VM-01", "VM-02"],
    "simulation_mode": True,
    "ransom_parameters": {"amount_usd": 500000}
}

events = run(config)  # Returns list[Event] matching schemas/event.json
```

### Standalone Execution

```bash
# Install dependencies
pip install -r requirements.txt

# Run with default config (config.yaml)
python main.py

# Run with custom config
python -c "
import yaml
from main import run

with open('config.yaml') as f:
    config = yaml.safe_load(f)
events = run(config)
print(f'Emitted {len(events)} events')
"
```

### Run Tests

```bash
python -m pytest tests/test_main.py -v
# or
python -m unittest tests.test_main -v
```

## Configuration

Default configuration is in `config.yaml`. Key options:

```yaml
vcenter_config:
  host: vcenter.citef.local
  username: domain_admin
  password: REDACTED_FOR_SECURITY

target_vms:
  - CITEF-VM-01
  - CITEF-VM-02

ransom_parameters:
  amount_usd: 500000
  currency: Bitcoin
  attacker_email: contact@ransomhub.local

target_file_extensions:
  - .docx
  - .xlsx
  - .pdf
  - .vmdk

simulation_mode: true  # Safety: disable to enable real execution
```

## Example Output

### Console & Log Output
```
================================================================================
Module 07: Ransomware Simulation - STARTED
================================================================================
[PHASE 1] Initial Access - vCenter Authentication
[SIM] Authentication successful

[PHASE 2] Reconnaissance - VM Enumeration
[SIM] Discovered 3 virtual machines

[PHASE 3] Defense Evasion - Backup Disabling
[SIM] Disabled 5 backup-related services

[PHASE 4] Impact - File Encryption
[SIM] Encrypted 12 files (docx, xlsx, pdf, vmdk)

[PHASE 5] Extortion - Ransom Note Deployment
[SIM] Deployed ransom notes

================================================================================
Module 07: Ransomware Simulation - COMPLETE
Events Emitted: 5
================================================================================
```

### Emitted Events

Events are emitted to `scenario_events.jsonl` in the standard NetStrike format:

```json
{
  "event_id": "550e8400-e29b-41d4-a716-446655440000",
  "timestamp": "2026-04-04T14:32:01Z",
  "phase": 7,
  "technique_id": "T1490",
  "tactic": "impact",
  "description": "Inhibited System Recovery - Disabled VSS shadow copies and backup services",
  "source_module": "07-ransomware-sim",
  "flag_triggered": null,
  "raw_data": {
    "backups_disabled": 5,
    "target_vms": ["CITEF-VM-01", "CITEF-VM-02", "CITEF-VM-03"]
  }
}
```

## Attack Phases

1. **Phase 1 - Initial Access**: vCenter Authentication
2. **Phase 2 - Reconnaissance**: Enumerate virtual machines and infrastructure
3. **Phase 3 - Defense Evasion**: Disable VSS and backup services
4. **Phase 4 - Impact**: Encrypt critical files
5. **Phase 5 - Extortion**: Deploy ransom notes

## Defensive Recommendations

1. **Access Control**: MFA for privileged accounts, principle of least privilege
2. **Backup Strategy**: Air-gapped, immutable backups with geographically dispersed storage
3. **Monitoring**: Detect VSS deletion, backup service stops, file encryption activity
4. **Network Segmentation**: Isolate ESXi infrastructure, restrict admin access
5. **Incident Response**: Maintain ransomware playbook and forensic procedures

## MITRE ATT&CK References

- **T1486**: Data Encrypted for Impact
- **T1490**: Inhibit System Recovery

## Troubleshooting

| Issue | Solution |
|-------|----------|
| vCenter connection timeout | Ensure `simulation_mode: true` for lab environments |
| No files encrypted | Create test files in `./data` with matching extensions |
| Permission errors | Run with appropriate file system permissions |

---

**Module Version**: 1.0  
**Last Updated**: April 2026
