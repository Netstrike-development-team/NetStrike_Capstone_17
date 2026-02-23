from fastapi import APIRouter, Depends

router = APIRouter(prefix="/users", tags=["users"])

# placeholder functions given the fact the behavior is not defined 

@router.post('/health')
def health():
    return

@router.post('/range/up')
def range_up():
    return

@router.post('/range/down')
def range_down():
    return