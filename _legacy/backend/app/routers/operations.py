"""Operations API"""

import httpx
from fastapi import APIRouter, HTTPException, Depends
from typing import List
from app.schemas.attack import (
    CreateOperationRequest,
    OperationResponse,
    AdversaryProfile
)
from app.services.caldera_client import CalderaClient

router = APIRouter(prefix="/operations", tags=["operations"])


def get_caldera_client() -> CalderaClient:
    return CalderaClient()


@router.post("", response_model=OperationResponse, status_code=201)
def create_operation(
    request: CreateOperationRequest,
    client: CalderaClient = Depends(get_caldera_client)
):
    """Create new operation"""
    try:
        result = client.create_operation(
            name=request.name,
            adversary_id=request.adversary_id,
            group=request.group
        )
        return OperationResponse(
            id=result["id"],
            name=result["name"],
            state=result["state"],
            adversary_id=result["adversary"]["adversary_id"],
            group=result["group"]
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        client.close()


@router.get("/{operation_id}", response_model=OperationResponse)
def get_operation(
    operation_id: str,
    client: CalderaClient = Depends(get_caldera_client)
):
    """Get operation status"""
    try:
        result = client.get_operation(operation_id)
        return OperationResponse(
            id=result["id"],
            name=result["name"],
            state=result["state"],
            adversary_id=result["adversary"]["adversary_id"],
            group=result["group"]
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        client.close()


@router.get("", response_model=List[OperationResponse])
def list_operations(
    client: CalderaClient = Depends(get_caldera_client)
):
    """List all operations"""
    try:
        result = client.list_operations()
        return [
            OperationResponse(
                id=op["id"],
                name=op["name"],
                state=op["state"],
                adversary_id=op["adversary"]["adversary_id"],
                group=op["group"]
            )
            for op in result
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        client.close()


@router.get("/adversaries/list", response_model=List[AdversaryProfile])
def list_adversaries(
    client: CalderaClient = Depends(get_caldera_client)
):
    """List available adversaries"""
    try:
        result = client.get_adversaries()
        return [
            AdversaryProfile(
                adversary_id=adv["adversary_id"],
                name=adv["name"],
                description=adv.get("description", "")
            )
            for adv in result
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        client.close()
