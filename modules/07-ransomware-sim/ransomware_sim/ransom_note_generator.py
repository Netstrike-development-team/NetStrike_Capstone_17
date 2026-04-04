"""
Ransom Note Generator - Generates RansomHub-style ransom notes
"""

import os
import logging
from datetime import datetime
from typing import Dict


logger = logging.getLogger(__name__)


class RansomNoteGenerator:
    """Generates ransom note files in the style of RansomHub"""
    
    def __init__(self, attacker_email: str, ransom_amount: str):
        self.attacker_email = attacker_email
        self.ransom_amount = ransom_amount
        self.ransom_notes = []
        logger.info("Ransom Note Generator initialized")
    
    def generate_ransom_note(self) -> str:
        """Generate ransom note content"""
        note = f"""
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

Provide {self.ransom_amount} USD in Bitcoin to recover your files.

Payment Address: 1RansomHub123456789ABCDEFGHIJKLMN
Payment Deadline: 7 days from now

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

HOW TO CONTACT US

Email: {self.attacker_email}
Onion Address: ransomhub.onion

Include your unique case ID in all communications:
CASE-ID-SIM-{datetime.now().strftime('%Y%m%d%H%M%S')}

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
        return note
    
    def write_ransom_note(self, target_directory: str, filename: str = "README_RANSOMHUB.txt") -> bool:
        """Write simulated ransom note to target directory"""
        try:
            if not os.path.exists(target_directory):
                logger.warning(f"Target directory {target_directory} does not exist (simulation)")
                return False
            
            note_path = os.path.join(target_directory, filename)
            note_content = self.generate_ransom_note()
            
            with open(note_path, 'w') as f:
                f.write(note_content)
            
            self.ransom_notes.append({
                "path": note_path,
                "timestamp": datetime.now().isoformat()
            })
            
            logger.info(f"[SIM] Ransom note written to {note_path}")
            return True
            
        except Exception as e:
            logger.error(f"Error writing ransom note to {target_directory}: {e}")
            return False
    
    def get_ransom_notes_report(self) -> Dict:
        """Generate report of ransom notes deployed"""
        return {
            "total_notes": len(self.ransom_notes),
            "notes": self.ransom_notes,
            "timestamp": datetime.now().isoformat()
        }
