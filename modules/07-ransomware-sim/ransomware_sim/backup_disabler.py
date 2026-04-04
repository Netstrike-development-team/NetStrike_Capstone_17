"""
Backup Disabler - Simulates disabling VSS and backup services
"""

import os
import logging
from datetime import datetime
from typing import Dict


logger = logging.getLogger(__name__)


class BackupDisabler:
    """Simulates disabling VSS shadow copies and backup jobs"""
    
    def __init__(self):
        self.disabled_backups = []
        logger.info("Backup Disabler initialized")
    
    def disable_vss_copies(self, simulate: bool = True) -> bool:
        """Simulate disabling Volume Shadow Copy Service"""
        logger.info("[SIM] Disabling VSS Shadow Copies")
        
        if simulate:
            self.disabled_backups.append({
                "service": "VSS",
                "action": "Disable shadow copies",
                "command": "vssadmin delete shadows /all /quiet",
                "status": "SIMULATED",
                "timestamp": datetime.now().isoformat()
            })
            logger.info("[SIM] VSS shadow copies disabled (simulated)")
            return True
        return False
    
    def disable_backup_jobs(self, simulate: bool = True) -> bool:
        """Simulate disabling backup jobs"""
        logger.info("[SIM] Disabling backup jobs")
        
        backup_jobs = [
            "Windows Server Backup",
            "Veeam Backup Service",
            "Commvault Galaxy",
            "Acronis Backup"
        ]
        
        if simulate:
            for job in backup_jobs:
                self.disabled_backups.append({
                    "service": job,
                    "action": "Disable scheduled backup job",
                    "status": "SIMULATED",
                    "timestamp": datetime.now().isoformat()
                })
            logger.info(f"[SIM] {len(backup_jobs)} backup jobs disabled (simulated)")
            return True
        return False
    
    def delete_backup_files(self, backup_directory: str, simulate: bool = True) -> int:
        """Simulate deletion of pre-staged backup files"""
        logger.info(f"[SIM] Removing backup files from {backup_directory}")
        
        deleted_count = 0
        
        if not os.path.exists(backup_directory):
            logger.warning(f"Backup directory {backup_directory} not found")
            return 0
        
        try:
            for item in os.listdir(backup_directory):
                if item.startswith(('.backup', '.bak', 'backup_')):
                    item_path = os.path.join(backup_directory, item)
                    
                    if simulate:
                        self.disabled_backups.append({
                            "type": "backup_file",
                            "path": item_path,
                            "action": "Delete backup file",
                            "status": "SIMULATED",
                            "timestamp": datetime.now().isoformat()
                        })
                        logger.info(f"[SIM] Would delete: {item_path}")
                        deleted_count += 1
        except Exception as e:
            logger.error(f"Error processing backup directory: {e}")
        
        logger.info(f"[SIM] {deleted_count} backup files marked for deletion (simulated)")
        return deleted_count
    
    def get_disabled_backups_report(self) -> Dict:
        """Generate report of disabled backups"""
        return {
            "total_disabled": len(self.disabled_backups),
            "backups": self.disabled_backups,
            "timestamp": datetime.now().isoformat()
        }
