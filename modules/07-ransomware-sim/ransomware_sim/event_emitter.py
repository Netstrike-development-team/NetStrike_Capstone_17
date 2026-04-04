"""
NetStrike Event Emitter - Standardized scenario event logging
"""

import json
import logging
import uuid
from datetime import datetime
from typing import Dict, Optional


logger = logging.getLogger(__name__)


class EventEmitter:
    """Emits standardized NetStrike scenario events"""
    
    def __init__(self, output_file: str = "scenario_events.jsonl"):
        self.output_file = output_file
        self.events_emitted = 0
        logger.info(f"Event Emitter initialized. Output: {output_file}")
    
    def emit_event(self,
                   phase: int,
                   technique_id: str,
                   tactic: str,
                   description: str,
                   source_module: str = "07-ransomware-sim",
                   flag_triggered: Optional[str] = None,
                   raw_data: Optional[Dict] = None) -> str:
        """
        Emit a standardized NetStrike event
        
        Args:
            phase: Attack phase (1-7)
            technique_id: MITRE ATT&CK technique (e.g., "T1486")
            tactic: MITRE ATT&CK tactic (e.g., "impact")
            description: Event description
            source_module: Source module name
            flag_triggered: Optional flag (e.g., "Flag 7 - Ransomware Deployed...")
            raw_data: Optional raw event data
        
        Returns:
            event_id: UUID of emitted event
        """
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
        
        # Write to JSONL file
        try:
            with open(self.output_file, 'a') as f:
                f.write(json.dumps(event) + '\n')
            
            self.events_emitted += 1
            logger.info(f"Event emitted [{event_id}]: {description}")
            
            return event_id
        except Exception as e:
            logger.error(f"Failed to emit event: {e}")
            return ""
    
    def get_events_count(self) -> int:
        """Get total events emitted"""
        return self.events_emitted
