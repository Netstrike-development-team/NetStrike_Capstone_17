from pydantic import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "MyAwesomeApp"
    DATABASE_URL: str
    SECRET_KEY: str

    class Config:
        env_file = ".env"

settings = Settings()