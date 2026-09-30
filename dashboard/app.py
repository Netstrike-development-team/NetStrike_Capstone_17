"""Authenticated FastAPI surface for participants and exercise staff."""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Response, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from orchestrator.controller import ControllerError
from orchestrator.evidence import render_csv, render_jsonl
from shared.actions import ActionContractError, ActionValidationError

from .auth import (
    PortalAuthenticationError,
    PortalAuthorizationError,
    PortalPrincipal,
    TokenAuthenticator,
)
from .service import PortalService
from .store import PortalStore


PARTICIPANT_ROLES = frozenset(
    {
        "incident_lead",
        "soc_analyst",
        "identity_responder",
        "endpoint_responder",
    }
)
FACILITATOR_ROLES = frozenset({"facilitator", "technical_operator"})


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ActionInput(StrictInput):
    action_id: str = Field(min_length=1, max_length=128)
    target_type: str = Field(min_length=1, max_length=64)
    target_id: str = Field(min_length=1, max_length=256)
    idempotency_key: str = Field(min_length=1, max_length=128)
    parameters: dict[str, Any] = Field(default_factory=dict)
    dry_run: bool = False


class EvidenceInput(StrictInput):
    reference_id: str = Field(min_length=1, max_length=256)
    source: str = Field(min_length=1, max_length=128)


class Dp1Input(StrictInput):
    affected_identity: str = Field(min_length=1, max_length=256)
    classification: str = Field(min_length=1, max_length=256)
    evidence: list[EvidenceInput] = Field(min_length=1, max_length=20)


class AdvanceInput(StrictInput):
    elapsed_seconds: int = Field(ge=0, le=10800)


class ItemInput(StrictInput):
    item_id: str = Field(min_length=1, max_length=128)


class SkipInput(ItemInput):
    reason: str = Field(min_length=1, max_length=512)


class StopInput(StrictInput):
    reason: str = Field(min_length=1, max_length=512)


class ResetInput(StrictInput):
    new_run_id: str | None = Field(default=None, min_length=1, max_length=128)


# Route closures intentionally share injected service/authentication state.
# pylint: disable=too-many-locals
def create_app(
    service: PortalService, authenticator: TokenAuthenticator
) -> FastAPI:
    """Create an app with injected state for offline operation and testing."""

    @asynccontextmanager
    async def lifespan(_app):
        async def drive_clock() -> None:
            while True:
                await asyncio.sleep(1)
                service.scheduler.tick()

        clock_task = asyncio.create_task(drive_clock())
        try:
            yield
        finally:
            clock_task.cancel()
            try:
                await clock_task
            except asyncio.CancelledError:
                pass

    app = FastAPI(
        title="Operation Silent Spider Portal API",
        version="1.0.0",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    static_root = Path(__file__).resolve().parent / "static"
    app.mount("/static", StaticFiles(directory=static_root), name="static")

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
            "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        )
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    def authorize(allowed_roles: frozenset[str]):
        def dependency(
            authorization: str | None = Header(default=None),
        ) -> PortalPrincipal:
            try:
                return authenticator.authenticate(
                    authorization, allowed_roles=allowed_roles
                )
            except PortalAuthenticationError as exc:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
                ) from exc
            except PortalAuthorizationError as exc:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
                ) from exc

        return dependency

    participant = authorize(PARTICIPANT_ROLES)
    facilitator = authorize(FACILITATOR_ROLES)

    def execute(operation):
        try:
            return operation()
        except (ControllerError, ActionContractError, ActionValidationError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail=str(exc)
            ) from exc

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "component": "netstrike-portal"}

    @app.get("/participant", include_in_schema=False)
    def participant_page() -> FileResponse:
        return FileResponse(static_root / "participant.html")

    @app.get("/facilitator", include_in_schema=False)
    def facilitator_page() -> FileResponse:
        return FileResponse(static_root / "facilitator.html")

    @app.get("/api/participant/state")
    def participant_state(
        _principal: PortalPrincipal = Depends(participant),
    ) -> dict[str, Any]:
        return service.participant_state()

    @app.post("/api/participant/actions")
    def participant_action(
        request: ActionInput,
        principal: PortalPrincipal = Depends(participant),
    ) -> dict[str, Any]:
        result = execute(
            lambda: service.submit_action(
                principal,
                action_id=request.action_id,
                target_type=request.target_type,
                target_id=request.target_id,
                idempotency_key=request.idempotency_key,
                parameters=request.parameters,
                dry_run=request.dry_run,
            )
        )
        if not result["successful"]:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=result)
        return result

    @app.post("/api/participant/checkpoints/dp1")
    def submit_dp1(
        request: Dp1Input,
        principal: PortalPrincipal = Depends(participant),
    ) -> dict[str, Any]:
        return execute(
            lambda: service.submit_dp1(
                principal,
                affected_identity=request.affected_identity,
                classification=request.classification,
                evidence=tuple(
                    (item.reference_id, item.source) for item in request.evidence
                ),
            )
        )

    @app.get("/api/facilitator/state")
    def facilitator_state(
        _principal: PortalPrincipal = Depends(facilitator),
    ) -> dict[str, Any]:
        return service.facilitator_state()

    @app.post("/api/facilitator/prepare")
    def prepare(
        _principal: PortalPrincipal = Depends(facilitator),
    ) -> dict[str, Any]:
        return execute(lambda: (service.run.controller.prepare(), service.facilitator_state())[1])

    @app.post("/api/facilitator/start")
    def start(
        _principal: PortalPrincipal = Depends(facilitator),
    ) -> dict[str, Any]:
        return execute(lambda: (service.scheduler.start(), service.facilitator_state())[1])

    @app.post("/api/facilitator/pause")
    def pause(
        _principal: PortalPrincipal = Depends(facilitator),
    ) -> dict[str, Any]:
        return execute(lambda: (service.scheduler.pause(), service.facilitator_state())[1])

    @app.post("/api/facilitator/resume")
    def resume(
        _principal: PortalPrincipal = Depends(facilitator),
    ) -> dict[str, Any]:
        return execute(lambda: (service.scheduler.resume(), service.facilitator_state())[1])

    @app.post("/api/facilitator/advance")
    def advance(
        request: AdvanceInput,
        _principal: PortalPrincipal = Depends(facilitator),
    ) -> dict[str, Any]:
        return execute(
            lambda: (
                service.scheduler.advance_to(request.elapsed_seconds),
                service.facilitator_state(),
            )[1]
        )

    @app.post("/api/facilitator/deliver")
    def deliver(
        request: ItemInput,
        _principal: PortalPrincipal = Depends(facilitator),
    ) -> dict[str, Any]:
        return execute(
            lambda: (
                service.run.controller.deliver(request.item_id),
                service.facilitator_state(),
            )[1]
        )

    @app.post("/api/facilitator/skip")
    def skip(
        request: SkipInput,
        _principal: PortalPrincipal = Depends(facilitator),
    ) -> dict[str, Any]:
        return execute(
            lambda: (
                service.run.controller.skip(request.item_id, request.reason),
                service.facilitator_state(),
            )[1]
        )

    @app.post("/api/facilitator/checkpoints/dp2")
    def resolve_dp2(
        _principal: PortalPrincipal = Depends(facilitator),
    ) -> dict[str, Any]:
        return execute(
            lambda: {
                "evaluation": PortalService.evaluation_dict(
                    service.run.resolve_dp2()
                ),
                "state": service.facilitator_state(),
            }
        )

    @app.post("/api/facilitator/stop")
    def stop(
        request: StopInput,
        _principal: PortalPrincipal = Depends(facilitator),
    ) -> dict[str, Any]:
        return execute(
            lambda: (
                service.run.fail_safe_stop(request.reason),
                service.facilitator_state(),
            )[1]
        )

    @app.post("/api/facilitator/reset")
    def reset(
        request: ResetInput,
        _principal: PortalPrincipal = Depends(facilitator),
    ) -> dict[str, Any]:
        return execute(
            lambda: (
                service.run.reset(new_run_id=request.new_run_id),
                service.scheduler.reset(),
                service.facilitator_state(),
            )[2]
        )

    def current_events() -> list[dict[str, Any]]:
        return service.store.events(
            service.run.definition.exercise_id, service.run.run_id
        )

    @app.get("/api/facilitator/exports/events.jsonl")
    def export_events_jsonl(
        _principal: PortalPrincipal = Depends(facilitator),
    ) -> Response:
        filename = f"{service.run.run_id}-events.jsonl"
        return Response(
            content=render_jsonl(current_events()),
            media_type="application/x-ndjson",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.get("/api/facilitator/exports/events.csv")
    def export_events_csv(
        _principal: PortalPrincipal = Depends(facilitator),
    ) -> Response:
        filename = f"{service.run.run_id}-events.csv"
        return Response(
            content=render_csv(current_events()),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    return app


def create_default_app() -> FastAPI:
    """Create the production app from runtime-injected offline configuration."""

    database_path = Path(
        os.getenv("NETSTRIKE_PORTAL_DATABASE", "output/netstrike-portal.sqlite3")
    )
    run_id = os.getenv("NETSTRIKE_RUN_ID")
    store = PortalStore(database_path)
    service = PortalService(store, run_id=run_id)
    return create_app(service, TokenAuthenticator.from_environment())
