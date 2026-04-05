# Module 07 - Usage Guide

Complete guide to configuring and using the ransomware simulation module.

---

## Quick Start

### Run with Default Settings

```bash
# Standalone mode: Create and encrypt fake files locally
python main.py --standalone

# Orchestrator mode: Simulate vCenter attack (requires vCenter config)
python main.py --config config.yaml
```

### Decrypt Encrypted Files

```bash
# Decrypt files encrypted in safe mode
python main.py --decrypt ./encrypted_copies --key 0123456789ABCDEF0123456789ABCDEF
```

---

## Configuration

### Configuration File (config.yaml)

The module is configured via `config.yaml`:

```yaml
# ============================================================================
# VCENTER CONFIGURATION
# ============================================================================
vcenter:
  host: vcenter.citef.local
  username: domain_admin
  password: REDACTED_FOR_SECURITY
  port: 443

# ============================================================================
# TARGET VIRTUAL MACHINES
# ============================================================================
target_vms:
  - CITEF-VM-01
  - CITEF-VM-02
  - DB-Server

# ============================================================================
# RANSOM PARAMETERS
# ============================================================================
ransom:
  amount: "$500,000"
  currency: "Bitcoin"
  attacker_email: contact@ransomhub.local
  deadline_days: 7

# ============================================================================
# FILE EXTENSIONS TO TARGET
# ============================================================================
file_extensions:
  - .vmdk
  - .docx
  - .xlsx
  - .pdf
  - .db

# ============================================================================
# ENCRYPTION MODE (Always enabled - choose between 'marker' or 'safe')
# ============================================================================
encryption:
  mode: "marker"  # "marker" (default) or "safe"
  static_key: "0123456789ABCDEF0123456789ABCDEF"  # 32 hex chars (only for safe mode)
  copy_destination: "./encrypted_copies"  # Where to copy files (only for safe mode)

# ============================================================================
# SIMULATION MODE (Educational use)
# ============================================================================
simulation_mode: true
logging:
  level: INFO
```

### Configuration Reference

**vCenter Configuration** (`vcenter` section)
- `host`: vCenter hostname or IP address
- `username`: Domain admin username (used for authentication)
- `password`: Domain admin password (keep secret!)
- `port`: vCenter API port (default: 443)
- Used in orchestrator mode only; ignored in standalone mode

**Target VMs** (`target_vms` section)
- List of virtual machine names to target
- The module will enumerate, disable VSS, and encrypt VMDK files for each VM
- Example: `["CITEF-VM-01", "CITEF-VM-02", "DB-Server"]`

**Ransom Parameters** (`ransom` section)
- `amount`: Ransom demand amount (string, e.g., "$500,000")
- `currency`: Currency type (e.g., "Bitcoin")
- `attacker_email`: Contact email for ransom negotiations
- `deadline_days`: Days until deadline
- These values appear in ransom notes and events

**File Extensions** (`file_extensions` section)
- List of file extensions the ransomware targets
- Informational in current version; can be used for filtering in extended implementations
- Common targets: `.vmdk`, `.docx`, `.xlsx`, `.pdf`, `.db`

**Encryption Mode** (`encryption` section)
- `mode`: Choose `"marker"` (default) or `"safe"`
  - `"marker"`: Creates `.RANSOMHUB` marker files (fast, non-destructive)
  - `"safe"`: AES-256 encryption with file copies (realistic, reversible)
- `static_key`: 32 hexadecimal characters for AES-256 key (only used in safe mode)
  - Must be exactly 32 chars of 0-9, A-F
  - Examples: `0123456789ABCDEF0123456789ABCDEF`, `DEADBEEFDEADBEEFDEADBEEFDEADBEEF`
- `copy_destination`: Directory for encrypted copies (only used in safe mode)

---

## Execution

### Standalone Mode

Create and encrypt fake files locally. Useful for:
- Validating encryption functionality
- Demonstrating the attack chain

```bash
# Default: Creates files in ./ransomware_test_files/
python main.py --standalone

# Custom directory
python main.py --standalone --test-dir /tmp/demo

# With custom config for encryption settings
python main.py --standalone --config custom-config.yaml
```

**What happens:**
1. Creates test directory (default: `./ransomware_test_files/`)
2. Creates 5 fake files (.docx, .xlsx, .pdf, .json, .txt)
3. Applies encryption (marker mode or safe mode)
4. Deploys ransom note
5. Outputs 5 events
6. Leaves encrypted files on disk for inspection

**Output:**
```
[INFO] RANSOMWARE SIMULATION - STANDALONE MODE
[INFO] Created test directory: /current/dir/ransomware_test_files
[INFO] Created fake file: important_file_1.docx
[INFO] Created fake file: important_file_2.xlsx
[INFO] [MARKER MODE] Marked file as encrypted: important_file_1.docx
[INFO] [MARKER MODE] Marked file as encrypted: important_file_2.xlsx
...
[INFO] Deployed ransom note to README_RANSOMHUB.txt
```

---

## Encryption Modes

### Marker Mode (Default)

The simplest encryption simulation mode. Creates `.RANSOMHUB` marker files.

**Configuration:**
```yaml
encryption:
  mode: "marker"
```

**Behavior:**
- Creates `.RANSOMHUB` marker file for each target file
- Appends encryption notice to original file
- **Does not** actually encrypt data
- Fast, no cryptographic overhead

**Example:**
```bash
python main.py --standalone
```

**Result:**
```
ransomware_test_files/
├── important_file_1.docx              # Original (unchanged content)
├── important_file_1.docx.RANSOMHUB    # Marker file
├── important_file_2.xlsx
├── important_file_2.xlsx.RANSOMHUB
├── important_file_3.pdf
├── important_file_3.pdf.RANSOMHUB
└── README_RANSOMHUB.txt               # Ransom note
```

**When to use:**
- Quick demonstrations
- Testing SIEM/EDR detection of marker files
- Lab environment without encryption setup
- Educational presentations

---

### Safe Mode (AES-256 Encryption)

Real AES-256-CBC encryption with easily reversible decryption.

**Configuration:**
```yaml
encryption:
  mode: "safe"
  static_key: "0123456789ABCDEF0123456789ABCDEF"  # 32 hex chars
  copy_destination: "./encrypted_copies"
```

**Behavior:**
- Copies each file to `copy_destination`
- Encrypts the copy with AES-256-CBC
- Random per-file IV stored with ciphertext
- Original files remain unchanged
- Easily reversible with the same key

**Example:**
```bash
# 1. Enable safe mode in config.yaml
# 2. Run standalone
python main.py --standalone
```

**Result:**
```
ransomware_test_files/                 # Originals - unchanged
├── important_file_1.docx
├── important_file_2.xlsx
├── important_file_3.pdf
└── ...

encrypted_copies/                      # Encrypted copies
├── important_file_1.docx              # Binary encrypted data
├── important_file_2.xlsx              # Binary encrypted data
├── important_file_3.pdf               # Binary encrypted data
└── ...
```

**Decryption:**
```bash
python main.py --decrypt ./encrypted_copies --key 0123456789ABCDEF0123456789ABCDEF
```

**When to use:**
- Realistic encryption testing
- SIEM detection validation with real encrypted files
- Demonstrating modern ransomware capabilities
- Testing recovery procedures
- Training and security assessments

**Technical Details:**
- Algorithm: AES-256-CBC (NIST standard)
- IV: Per-file random 16-byte initialization vector
- Format: `[16-byte IV][Encrypted Data]`
- Key: Static hex string (256-bit)
- Padding: PKCS7

**Security Note:** This is designed to be easily reversible for testing. The static key is visible in config files, so this is NOT for production systems.

---

## Decryption

### Decrypt Files Encrypted in Safe Mode

```bash
python main.py --decrypt ./encrypted_copies --key 0123456789ABCDEF0123456789ABCDEF
```

**Parameters:**
- `--decrypt`: Directory containing encrypted files
- `--key`: 32-character hex encryption key

**Output:**
```
[INFO] RANSOMWARE SIMULATION - DECRYPTION MODE
[INFO] Decrypted file: important_file_1.docx (1024 → 512 bytes)
[INFO] Decrypted file: important_file_2.xlsx (2048 → 1536 bytes)
[INFO] Decryption complete: 3 files decrypted
```

### Verify Decryption

Check that files were successfully decrypted:

```bash
# View file size info
ls -lh encrypted_copies/

# Verify content (for text files)
head -c 100 encrypted_copies/important_file_5.txt
```

---

## Usage Examples

### Example 1: Basic Standalone Test (Marker Mode)

```bash
# Uses default config with marker mode
python main.py --standalone

# Check results
ls -la ransomware_test_files/

# View ransom note
cat ransomware_test_files/README_RANSOMHUB.txt
```

### Example 2: Real Encryption (Safe Mode)

```bash
# Edit config.yaml to use safe mode
# encryption:
#   mode: "safe"
#   static_key: "0123456789ABCDEF0123456789ABCDEF"
#   copy_destination: "./encrypted_copies"

python main.py --standalone

# Check original files (unchanged)
ls ransomware_test_files/

# Check encrypted copies
ls encrypted_copies/

# Decrypt when done
python main.py --decrypt ./encrypted_copies --key 0123456789ABCDEF0123456789ABCDEF

# Verify decryption
ls encrypted_copies/
```

### Example 3: Custom Test Directory

```bash
# Create in custom location
python main.py --standalone --test-dir /tmp/ransomware_demo

# View results
ls -la /tmp/ransomware_demo/
```

### Example 4: Orchestrator Mode (vCenter)

```bash
# Create/configure config.yaml with vCenter details
# Then run:
python main.py --config config.yaml

# Output shows simulated attack chain
# Events are printed to stdout in JSON format
```

### Example 5: Change Encryption Key

```yaml
# config.yaml
encryption:
  mode: "safe"
  static_key: "DEADBEEFDEADBEEFDEADBEEFDEADBEEF"  # Different key!
  copy_destination: "./test_demo"
```

```bash
python main.py --standalone

# Later, decrypt with the same key
python main.py --decrypt ./test_demo --key DEADBEEFDEADBEEFDEADBEEFDEADBEEF
```

### Example 6: Python API Usage

```python
#!/usr/bin/env python3
from main import run, run_standalone
import yaml

# Orchestrator mode
with open('config.yaml') as f:
    config = yaml.safe_load(f)

events = run(config)
for event in events:
    print(f"{event['technique_id']}: {event['description']}")

# Standalone mode
events = run_standalone('./test_directory')
print(f"Generated {len(events)} events")
```

---

## Testing

### Install Dependencies

```bash
pip install -r requirements.txt
```

### Run Unit Tests

```bash
# Run all tests
python -m pytest tests/test_main.py -v

# Run specific test
python -m pytest tests/test_main.py::test_event_generation -v
```

---

## Troubleshooting

### Encryption Key Format Error

```
ValueError: Key must be 32 hex characters
```

**Solution:**
- Ensure key is exactly 32 characters
- Use only 0-9 and A-F characters
- Check for leading/trailing whitespace

**Example valid keys:**
```
0123456789ABCDEF0123456789ABCDEF
DEADBEEFDEADBEEFDEADBEEFDEADBEEF
A1B2C3D4E5F6A7B8C9D0E1F2A3B4C5D6
```

### Decryption Fails

```
Error: Unable to decrypt file
```

**Possible causes:**
- Using wrong encryption key
- File was encrypted with different key
- File is corrupted
- File is not actually encrypted (marker mode)

**Solution:**
- Double-check the key matches what was used for encryption
- Ensure you're using the same `encryption.static_key` from config
- Verify file is actually encrypted (starts with random bytes)

### Files Not Encrypted

Check the logs for:
- `mode: "marker"` in config (creates markers instead of encryption)
- Invalid encryption key format
- Missing `pycryptodome` package

**Solutions:**
```bash
# Check current config
cat config.yaml | grep -A3 "\[encryption\]"

# Verify pycryptodome is installed
pip list | grep pycryptodome

# Install missing dependencies
pip install pycryptodome
```

### Module Import Errors

```
ModuleNotFoundError: No module named 'encryption'
```

**Solution:**
Make sure you're running from the correct directory:

```bash
cd modules/07-ransomware-sim/
python main.py --standalone
```

---

## Command Reference

```bash
# Standalone mode with default settings
python main.py --standalone

# Standalone with custom directory
python main.py --standalone --test-dir /path/to/dir

# Standalone with custom config
python main.py --standalone --config custom.yaml

# Orchestrator mode with custom config
python main.py --config config.yaml

# Decrypt encrypted files
python main.py --decrypt /path/to/encrypted --key HEXKEY

# Show help
python main.py --help
```

---

## Return to OVERVIEW.md

For architecture details, attack chain explanation, and technical information, see [README.md](README.md).
