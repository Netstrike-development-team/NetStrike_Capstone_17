"""
NetStrike Ransomware Simulator - Main orchestrator
"""

import json
import logging
from dataclasses import asdict
from datetime import datetime
from typing import Dict

from .config import SimulationConfig
from .event_emitter import EventEmitter
from .vcenter_connector import vCenterConnector
from .encryption_simulator import FileEncryptionSimulator
from .backup_disabler import BackupDisabler
from .ransom_note_generator import RansomNoteGenerator


logger = logging.getLogger(__name__)


class RansomwareSimulator:
    """Main orchestrator for ransomware simulation"""
    
    def __init__(self, config: SimulationConfig):
        self.config = config
        self.vcenter = vCenterConnector(
            config.vcenter_host,
            config.vcenter_user,
            config.vcenter_password
        )
        self.encryptor = FileEncryptionSimulator(config.encryption_key)
        self.backup_disabler = BackupDisabler()
        self.ransom_generator = RansomNoteGenerator(
            config.attacker_email,
            config.ransom_amount
        )
        self.event_emitter = EventEmitter()
        self.execution_log = []
        logger.info("Ransomware Simulator initialized")
    
    def execute_attack(self) -> Dict:
        """Execute full ransomware attack simulation"""
        logger.info("=" * 80)
        logger.info("RANSOMWARE SIMULATION ATTACK SEQUENCE INITIATED")
        logger.info("=" * 80)
        
        attack_report = {
            "simulation_start": datetime.now().isoformat(),
            "config": asdict(self.config),
            "phases": {},
            "events_emitted": 0
        }
        
        # Phase 1: vCenter Authentication
        logger.info("\n[PHASE 1] Initial Access - vCenter Authentication")
        if self.vcenter.authenticate(simulate=self.config.simulate_only):
            attack_report["phases"]["phase_1_auth"] = {
                "status": "SUCCESS",
                "session_id": self.vcenter.session_id
            }
        else:
            attack_report["phases"]["phase_1_auth"] = {"status": "FAILED"}
            return attack_report
        
        # Phase 2: Enumerate VMs
        logger.info("\n[PHASE 2] Reconnaissance - VM Enumeration")
        vms = self.vcenter.get_vm_list()
        attack_report["phases"]["phase_2_recon"] = {
            "vms_discovered": len(vms),
            "vm_details": vms
        }
        
        # Phase 3: Disable Backups and VSS
        logger.info("\n[PHASE 3] Defense Evasion - Backup Disabling")
        self.backup_disabler.disable_vss_copies(self.config.simulate_only)
        self.backup_disabler.disable_backup_jobs(self.config.simulate_only)
        self.backup_disabler.delete_backup_files("./backups", self.config.simulate_only)
        attack_report["phases"]["phase_3_defense"] = \
            self.backup_disabler.get_disabled_backups_report()
        
        # Emit event for backup disablement (T1490)
        event_id = self.event_emitter.emit_event(
            phase=7,
            technique_id="T1490",
            tactic="impact",
            description="Inhibited System Recovery - Disabled VSS shadow copies and backup services",
            source_module="07-ransomware-sim",
            flag_triggered=None,
            raw_data={
                "backups_disabled": attack_report["phases"]["phase_3_defense"]["total_disabled"],
                "target_vms": self.config.target_vms
            }
        )
        
        # Phase 4: File Encryption
        logger.info("\n[PHASE 4] Impact - File Encryption")
        target_files = self.encryptor.identify_target_files(
            "./data",
            self.config.file_extensions_to_target,
            max_files=20
        )
        
        for file_path in target_files:
            self.encryptor.simulate_encryption(file_path)
        
        attack_report["phases"]["phase_4_encryption"] = \
            self.encryptor.get_encrypted_files_report()
        
        # Emit event for file encryption (T1486)
        event_id = self.event_emitter.emit_event(
            phase=7,
            technique_id="T1486",
            tactic="impact",
            description=f"Data Encrypted for Impact - Encrypted {attack_report['phases']['phase_4_encryption']['total_encrypted']} files",
            source_module="07-ransomware-sim",
            flag_triggered=None,
            raw_data={
                "files_encrypted": attack_report["phases"]["phase_4_encryption"]["total_encrypted"],
                "target_extensions": self.config.file_extensions_to_target,
                "target_vms": self.config.target_vms
            }
        )
        
        # Phase 5: Ransom Note Deployment
        logger.info("\n[PHASE 5] Extortion - Ransom Note Deployment")
        ransom_deployed = self.ransom_generator.write_ransom_note("./")
        attack_report["phases"]["phase_5_ransom"] = {
            "note_deployed": ransom_deployed,
            "notes_report": self.ransom_generator.get_ransom_notes_report()
        }
        
        # Emit final event for ransomware deployment (Flag 7)
        event_id = self.event_emitter.emit_event(
            phase=7,
            technique_id="T1486",
            tactic="impact",
            description="Ransomware payload deployed - Full attack chain executed successfully",
            source_module="07-ransomware-sim",
            flag_triggered="Flag 7 - Ransomware Deployed: Attacker has deployed a ransomware payload on an ESXi cluster",
            raw_data={
                "total_files_encrypted": attack_report["phases"]["phase_4_encryption"]["total_encrypted"],
                "total_backups_disabled": attack_report["phases"]["phase_3_defense"]["total_disabled"],
                "ransom_notes_deployed": attack_report["phases"]["phase_5_ransom"]["notes_report"]["total_notes"],
                "vcenter_target": self.config.vcenter_host,
                "target_vms": self.config.target_vms,
                "ransom_amount": self.config.ransom_amount
            }
        )
        
        attack_report["simulation_end"] = datetime.now().isoformat()
        attack_report["events_emitted"] = self.event_emitter.get_events_count()
        
        logger.info("\n" + "=" * 80)
        logger.info("RANSOMWARE SIMULATION COMPLETE")
        logger.info(f"Events Emitted: {attack_report['events_emitted']}")
        logger.info("=" * 80)
        
        self.vcenter.disconnect()
        
        return attack_report
    
    def generate_report(self, report: Dict, output_file: str = "attack_report.json"):
        """Generate comprehensive attack report"""
        try:
            with open(output_file, 'w') as f:
                json.dump(report, f, indent=2)
            logger.info(f"Attack report saved to {output_file}")
        except Exception as e:
            logger.error(f"Error saving report: {e}")
