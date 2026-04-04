"""
File Encryption Simulator - Simulates AES encryption on target files
"""

import os
import logging
from datetime import datetime
from typing import Dict, List


logger = logging.getLogger(__name__)


class FileEncryptionSimulator:
    """Simulates AES encryption on decoy files without actual encryption"""
    
    def __init__(self, encryption_key: str):
        self.encryption_key = encryption_key
        self.encrypted_files = []
        logger.info("File Encryption Simulator initialized")
    
    def identify_target_files(self, 
                            directory: str, 
                            extensions: List[str],
                            max_files: int = 10) -> List[str]:
        """Identify files matching target extensions (simulation safe)"""
        target_files = []
        
        if not os.path.exists(directory):
            logger.warning(f"Directory {directory} does not exist (simulation)")
            return target_files
        
        try:
            for root, dirs, files in os.walk(directory):
                for file in files:
                    if any(file.lower().endswith(ext) for ext in extensions):
                        target_files.append(os.path.join(root, file))
                        if len(target_files) >= max_files:
                            break
                if len(target_files) >= max_files:
                    break
        except Exception as e:
            logger.error(f"Error scanning directory {directory}: {e}")
        
        logger.info(f"[SIM] Identified {len(target_files)} target files")
        return target_files
    
    def simulate_encryption(self, file_path: str) -> bool:
        """Simulate file encryption - creates marker, doesn't actually encrypt"""
        try:
            if not os.path.exists(file_path):
                logger.warning(f"File {file_path} not found (skipped)")
                return False
            
            # Create encrypted marker file instead of actually encrypting
            encrypted_marker = f"{file_path}.RANSOMHUB"
            with open(encrypted_marker, 'w') as f:
                f.write(f"[SIM] This file has been marked as encrypted: {file_path}\n")
                f.write(f"Original size: {os.path.getsize(file_path)} bytes\n")
            
            self.encrypted_files.append({
                "original_path": file_path,
                "marker_file": encrypted_marker,
                "timestamp": datetime.now().isoformat()
            })
            
            logger.info(f"[SIM] Encrypted marker created for {file_path}")
            return True
            
        except Exception as e:
            logger.error(f"Error processing {file_path}: {e}")
            return False
    
    def get_encrypted_files_report(self) -> Dict:
        """Generate report of encrypted files"""
        return {
            "total_encrypted": len(self.encrypted_files),
            "files": self.encrypted_files,
            "timestamp": datetime.now().isoformat()
        }
