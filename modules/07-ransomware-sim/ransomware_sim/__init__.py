"""
NetStrike Ransomware Simulation Package

Provides modular components for simulating ransomware attacks in a controlled
lab environment for educational and testing purposes.
"""

from .config import SimulationConfig
from .event_emitter import EventEmitter
from .vcenter_connector import vCenterConnector
from .encryption_simulator import FileEncryptionSimulator
from .backup_disabler import BackupDisabler
from .ransom_note_generator import RansomNoteGenerator
from .simulator import RansomwareSimulator

__all__ = [
    "SimulationConfig",
    "EventEmitter",
    "vCenterConnector",
    "FileEncryptionSimulator",
    "BackupDisabler",
    "RansomNoteGenerator",
    "RansomwareSimulator",
]
