# Module 06-cloud-exfil

MITRE Tactics: Collection (TA0009) • Exfiltration (TA0010)  •  T1530, T1537, T1567, T1048

The attacker uses harvested cloud credentials to access the AWS environment and exfiltrate simulated customer PII data from S3 storage, replicating the Scattered Spider data theft model.

### What the Attacker Does

- Authenticates to AWS using IAM credentials found in emails or configuration files on compromised workstations
- Creates a new IAM backdoor user for persistence
- Enumerates S3 buckets and identifies the customer database bucket
- Exfiltrates data via AWS CLI commands, routing through TOR/VPN proxies to simulate operational security
- Prepares an extortion demand referencing the stolen data

### Simulation Implementation
- A simulated AWS-equivalent environment within CITEF is pre-populated with synthetic customer PII records
- The Cloud Exfiltration Module executes the S3 enumeration and download sequence using AWS CLI against the simulated environment
- Exfiltrated data volume and timing are logged for detection evaluation

---

## Component Breakdown

### **Cloud Exfiltration Module**
The orchestrator of the simulation.  
Responsible for:

- IAM authentication  
- Backdoor user creation  
- Bucket enumeration  
- Object download  
- Exfiltration simulation  
- Extortion note generation  
- Logging  

### **Mock IAM Service**
Simulates AWS IAM:

- User store 
- Access key validation  
- Role assignment  
- Backdoor user creation  

### **Mock S3 Storage**
Simulates AWS S3:

- Bucket listing  
- Object listing  
- Synthetic PII object retrieval  

### **Logging Subsystem**
Captures:

- Authentication attempts  
- IAM user creation  
- Bucket enumeration  
- Object downloads  
- Exfiltration timing and volume  
- Extortion note generation  

### **Output Artifacts**
- `extortion_note.txt`  
- Exfiltrated synthetic PII files  
- Log files (e.g., `cloud_pivot_and_exfil_sim.log`) 
---

## Purpose of This Module

This module helps teams:

- Understand attacker behavior in cloud environments  
- Validate cloud monitoring and alerting  
- Improve detection logic for identity misuse and data theft  
- Strengthen incident‑response readiness  
- Practice handling extortion‑style scenarios safely  

---

## Architecture 

modules/
  06-cloud-exfil/
    cloud_exfil.py
    tests/
      __init__.py        
      test_cloud_exfil.py

--- 

## Testing

Unit tests are included under the `tests/` directory. These tests validate:

- IAM authentication  
- Backdoor user creation  
- Bucket and object enumeration  
- Synthetic object download  
- End‑to‑end simulation execution  

---
