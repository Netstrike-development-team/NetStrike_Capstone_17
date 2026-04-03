"""Caldera API client"""

import httpx
from typing import Dict, List
from app.core.config import get_settings


class CalderaClient:
    """Client for Caldera C2 API"""
    
    def __init__(self):
        self.settings = get_settings()
        self.base_url = self.settings.caldera_url
        self.api_key = self.settings.caldera_api_key
        self.client = httpx.Client(timeout=30.0)
    
    def _headers(self) -> Dict[str, str]:
        """API headers"""
        return {
            "KEY": self.api_key,
            "Content-Type": "application/json"
        }
    
    def create_operation(self, name: str, adversary_id: str, group: str = "red") -> Dict:
        """Create operation"""
        url = f"{self.base_url}/api/v2/operations"
        payload = {
            "name": name,
            "adversary": {"adversary_id": adversary_id},
            "group": group,
            "state": "running",
            "auto_close": False
        }
        response = self.client.post(url, json=payload, headers=self._headers())
        response.raise_for_status()
        return response.json()
    
    def get_operation(self, operation_id: str) -> Dict:
        """Get operation by ID"""
        url = f"{self.base_url}/api/v2/operations/{operation_id}"
        response = self.client.get(url, headers=self._headers())
        response.raise_for_status()
        return response.json()
    
    def list_operations(self) -> List[Dict]:
        """List all operations"""
        url = f"{self.base_url}/api/v2/operations"
        response = self.client.get(url, headers=self._headers())
        response.raise_for_status()
        return response.json()
    
    def get_adversaries(self) -> List[Dict]:
        """List available adversaries"""
        url = f"{self.base_url}/api/v2/adversaries"
        response = self.client.get(url, headers=self._headers())
        response.raise_for_status()
        return response.json()
    
    def close(self):
        """Close client"""
        self.client.close()
