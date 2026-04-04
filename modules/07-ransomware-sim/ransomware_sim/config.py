"""
NetStrike Ransomware Simulation - Configuration and Types
"""

from dataclasses import dataclass
from typing import List


@dataclass
class SimulationConfig:
    """Configuration for ransomware simulation"""
    vcenter_host: str = "vcenter.citef.local"
    vcenter_user: str = "domain_admin"
    vcenter_password: str = "REDACTED"
    target_vms: List[str] = None
    encryption_key: str = "SimulatedEncryptionKey123456789012"  # 32 bytes for AES-256
    ransom_amount: str = "$500,000"
    ransom_currency: str = "Bitcoin"
    attacker_email: str = "ransom@ransomhub.local"
    file_extensions_to_target: List[str] = None
    simulate_only: bool = True  # Safety flag
    
    def __post_init__(self):
        if self.target_vms is None:
            self.target_vms = ["CITEF-VM-01", "CITEF-VM-02", "CITEF-VM-03"]
        if self.file_extensions_to_target is None:
            self.file_extensions_to_target = [
                ".docx", ".xlsx", ".pdf", ".txt", ".jpg", ".png",
                ".vmdk", ".iso"
            ]
