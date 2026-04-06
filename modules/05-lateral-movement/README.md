# Module 5 : Lateral Movement

## Overview
This module performs **Active Directory enumeration** and generates audit data for use in our **threat‑simulation environment**.  
It supports the *Discovery*, *Privilege Escalation* and *Lateral Movement* phases of a simulated attack, producing realistic data and expected behaviors.

The module collects:

- Domain users  
- Security groups  
- Computer objects  
- Account metadata (UAC flags, timestamps, group memberships)  

All results are exported to structured CSV files and logged for detection scoring.

---

## Purpose
This module is used during **Phase 5: Discovery & Lateral Movement** of the simulation.  
It provides attacker‑like enumeration activity while remaining fully safe and non‑intrusive.

### MITRE ATT&CK Techniques (Defensive Mapping)

| Technique ID | Name |
|--------------|------|
| **T1069** | Permission Groups Discovery |
| **T1087** | Account Discovery |
| **T1021** | Remote Services *(simulated)* |
| **T1550** | Use of Stolen Credentials *(simulated)* |

Privilege escalation and lateral movement are **simulated** using pre‑staged credentials.

---

## Features

### ✔ Active Directory Enumeration
Retrieves:

- User accounts  
- Group objects  
- Computer objects  
- Account hygiene indicators  
- Group memberships  

### ✔ Architecture
05-lateral-movement/project-root/
├── ad_enum_simulated_escalation.py
├── README.md
├── output/
│   ├── logs/
│   │   └── ad_audit.log              # Runtime log file (auto-generated)
│   └── audits/
│       ├── ad_users_audit.csv        # Exported user enumeration
│       ├── ad_groups_audit.csv       # Exported group enumeration
│       └── ad_computers_audit.csv    # Exported computer enumeration
│
└── tests/
    └── test_ad_enum.py               # Unit tests for helper functions, CSV export, logging, etc.

### ✔ Logging
Logs include:

- Connection attempts  
- Enumeration steps  
- Export operations  
- Simulated escalation events  

### ✔ Simulated Privilege Escalation
The module logs staged transitions such as:

Stage escalation: STANDARD_USER -> PRIVILEGED_USER Privilege escalation is simulated using pre-staged credential: simcorp\svc-admin-tier1


---

## Simulated Escalation
To support the threat‑simulation storyline, the module includes staged transitions:

1. **Standard User → Privileged User**  
2. **Privileged User → Domain Admin**  
3. **Domain Admin → Infrastructure / Cloud Admin**  

Each transition is logged using **pre‑staged, non‑functional credentials**.

No real escalation, credential theft, or offensive techniques are performed.

---

## Prerequisites

- Python 3.8+  
- Network access to a domain controller  
- A valid domain user credential (read‑only LDAP queries)  
- `ldap3` Python package (auto‑installed if missing)

---

## Configuration

Update the following values to match your lab environment:

```python
AD_SERVER = "ldap://<domain-controller>"
BASE_DN = "DC=simcorp,DC=com"

The script automatically detects the current user:
AD_USER = f"{DOMAIN}\\{USERNAME}"
