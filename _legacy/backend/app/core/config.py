"""Application configuration"""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings"""
    
    # API Settings
    app_name: str = "NetStrike Cyber Range"
    debug: bool = True
    
    # Caldera Settings
    caldera_url: str = "http://localhost:8888"
    caldera_api_key: str = "ADMIN123"
    
    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()
