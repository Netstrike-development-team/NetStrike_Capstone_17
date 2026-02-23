""""User routes"""

from fastapi import APIRouter

router = APIRouter(prefix="/users", tags=["users"])

# placeholder functions given the fact the behavior is not defined 

"""Health route configuration"""
@router.post('/health')
def health():
    return

"""Range-up route configuration"""
@router.post('/range/up')
def range_up():
    return

"""Range-down route configuration"""
@router.post('/range/down')
def range_down():
    return
