"""User routes"""

from fastapi import APIRouter

router = APIRouter(prefix="/users", tags=["users"])

# placeholder functions given the fact the behavior is not defined
@router.post('/health')
def health():
    """Health route configuration"""
    return

@router.post('/range/up')
def range_up():
    """Range-up route configuration"""
    return

@router.post('/range/down')
def range_down():
    """Range-down route configuration"""
    return
