"""NetStrike Backend"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import operations
from app.core.config import get_settings

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    description="Cyber range platform",
    version="0.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(operations.router, prefix="/api/v1")


@app.get("/")
def root():
    return {"status": "healthy", "app": settings.app_name}
