#!/usr/bin/env python3
"""
Module 07 - Ransomware Simulation
Entry point for orchestrator integration

This module simulates a modern ransomware attack targeting VMware ESXi infrastructure.
Emits standardized events following the NetStrike event schema.
"""

import logging
import sys
from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime
import json

# Add package to path
sys.path.insert(0, str(Path(__file__).parent))

from ransomware_sim import (
    SimulationConfig,
    RansomwareSimulator,
    EventEmitter
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class RansomwareEventCollector:
    """Collects events from the ransomware simulator in-memory"""
    
    def __init__(self, output_file: str = "scenario_events.jsonl"):
        self.events: List[Dict[str, Any]] = []
        self.output_file = output_file
    
    def emit_event(self,
                   phase: int,
                   technique_id: str,
                   tactic: str,
                   description: str,
                   source_module: str = "07-ransomware-sim",
                   flag_triggered: str = None,
                   raw_data: Dict = None) -> str:
        """
        Emit a standardized NetStrike event and collect it in-memory.
        
        Args:
            phase: Attack phase (1-7)
            technique_id: MITRE ATT&CK technique (e.g., "T1486")
            tactic: MITRE ATT&CK tactic (e.g., "impact")
            description: Event description
            source_module: Source module name
            flag_triggered: Optional flag
            raw_data: Optional raw event data
        
        Returns:
            event_id: UUID of emitted event
        """
        import uuid
        
        event_id = str(uuid.uuid4())
        timestamp = datetime.utcnow().isoformat() + "Z"
        
        event = {
            "event_id": event_id,
            "timestamp": timestamp,
            "phase": phase,
            "technique_id": technique_id,
            "tactic": tactic,
            "description": description,
            "source_module": source_module,
            "flag_triggered": flag_triggered,
            "raw_data": raw_data or {}
        }
        
        self.events.append(event)
        
        # Also write to JSONL for audit logging
        try:
            with open(self.output_file, 'a') as f:
                f.write(json.dumps(event) + '\n')
        except Exception as e:
            logger.error(f"Failed to write event to JSONL: {e}")
        
        logger.info(f"Event [{event_id}]: {description}")
        return event_id
    
    def get_events(self) -> List[Dict[str, Any]]:
        """Get all collected events"""
        return self.events


def run(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Execute ransomware simulation and return standardized events.
    
    This is the main entry point called by the orchestrator.
    
    Args:
        config: Configuration dictionary with the following structure:
            {
                "vcenter_config": {
                    "host": "vcenter.citef.local",
                    "username": "domain_admin",
                    "password": "REDACTED",
                    "port": 443
                },
                "target_vms": ["VM1", "VM2", ...],
                "simulation_mode": true,  # Safety flag
                "ransom_parameters": {...},
                "target_file_extensions": [...],
                ...
            }
    
    Returns:
        List[Dict]: Standardized events matching schemas/event.json
    
    Example:
        ```python
        from main import run
        
        config = {
            "vcenter_config": {"host": "vcenter.citef.local", ...},
            "target_vms": ["CITEF-VM-01", "CITEF-VM-02"],
            "simulation_mode": True
        }
        
        events = run(config)
        for event in events:
            print(f"{event['timestamp']} - {event['description']}")
        ```
    """
    logger.info("=" * 80)
    logger.info("Module 07: Ransomware Simulation - STARTED")
    logger.info("=" * 80)
    
    # Initialize event collector
    event_collector = RansomwareEventCollector()
    
    # Build configuration from input
    vcenter_conf = config.get('vcenter_config', {})
    ransom_conf = config.get('ransom_parameters', {})
    
    sim_config = SimulationConfig(
        vcenter_host=vcenter_conf.get('host', 'vcenter.citef.local'),
        vcenter_user=vcenter_conf.get('username', 'domain_admin'),
        vcenter_password=vcenter_conf.get('password', 'REDACTED'),
        target_vms=config.get('target_vms'),
        ransom_amount=f"${ransom_conf.get('amount_usd', 500000)}",
        ransom_currency=ransom_conf.get('currency', 'Bitcoin'),
        attacker_email=ransom_conf.get('attacker_email', 'contact@ransomhub.local'),
        file_extensions_to_target=config.get('target_file_extensions'),
        simulate_only=config.get('simulation_mode', True)
    )
    
    # Override event emitter to use our collector
    try:
        sim = RansomwareSimulator(sim_config)
        
        # Replace the event emitter with our collector
        sim.event_emitter = event_collector
        
        # Execute attack
        logger.info("Executing attack sequence...")
        report = sim.execute_attack()
        
        # Log summary
        logger.info("=" * 80)
        logger.info("Module 07: Ransomware Simulation - COMPLETE")
        logger.info(f"Events Emitted: {len(event_collector.events)}")
        logger.info("=" * 80)
        
        return event_collector.get_events()
    
    except Exception as e:
        logger.error(f"Error during ransomware simulation: {e}", exc_info=True)
        
        # Emit error event
        error_event = {
            "event_id": str(__import__('uuid').uuid4()),
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "phase": 0,
            "technique_id": "UNKNOWN",
            "tactic": "error",
            "description": f"Ransomware simulation error: {str(e)}",
            "source_module": "07-ransomware-sim",
            "flag_triggered": None,
            "raw_data": {"error": str(e)}
        }
        
        return [error_event]


if __name__ == "__main__":
    """
    Standalone execution for testing
    """
    import yaml
    
    # Load default config
    config_file = Path(__file__).parent / "config.yaml"
    
    if not config_file.exists():
        logger.error(f"Config file not found: {config_file}")
        sys.exit(1)
    
    with open(config_file, 'r') as f:
        config = yaml.safe_load(f)
    
    # Execute
    events = run(config)
    
    # Print summary
    print("\n" + "=" * 80)
    print("RANSOMWARE SIMULATION - EVENT SUMMARY")
    print("=" * 80)
    print(f"Total Events: {len(events)}\n")
    
    for event in events:
        print(f"[{event['timestamp']}] {event['tactic'].upper()}")
        print(f"  Technique: {event['technique_id']}")
        print(f"  Description: {event['description']}")
        if event.get('flag_triggered'):
            print(f"  Flag: {event['flag_triggered']}")
        print()
    
    print("=" * 80)
    print(f"Events saved to: scenario_events.jsonl")
