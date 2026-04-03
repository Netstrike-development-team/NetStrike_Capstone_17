"""Attack schemas"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


class OperationState(str, Enum):
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "finished"
    ERROR = "error"


class CreateOperationRequest(BaseModel):
    """Create operation request"""
    name: str = Field(..., description="Operation name")
    adversary_id: str = Field(..., description="Adversary profile ID")
    group: str = Field(default="red", description="Target group")


class OperationResponse(BaseModel):
    """Operation response"""
    id: str
    name: str
    state: OperationState
    adversary_id: str
    group: str


class AdversaryProfile(BaseModel):
    """Adversary profile"""
    adversary_id: str
    name: str
    description: Optional[str] = None
