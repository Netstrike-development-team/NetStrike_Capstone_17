"""Authenticated FastAPI surface for participants and exercise staff."""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Iterable

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, status
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
from .identity_audit import IdentityAuditError
from .origin import OriginAllowlist, OriginDeniedError
from .service import PortalService
from .sso import SsoBoundaryError, SsoExperienceError
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
IDENTITY_CAPTURE_ROLES = frozenset({"identity_capture_service"})
MAX_IDENTITY_CAPTURE_BYTES = 16 * 1024
MAX_SSO_REQUEST_BYTES = 4 * 1024


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


class MfaDecisionInput(StrictInput):
    challenge_id: str = Field(min_length=1, max_length=128)
    decision: str = Field(pattern="^(approve|deny)$")


# Route closures intentionally share injected service/authentication state.
# pylint: disable=too-many-locals,too-many-statements
def create_app(
    service: PortalService,
    authenticator: TokenAuthenticator,
    *,
    sso_allowed_origins: Iterable[str],
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
    sso_origins = OriginAllowlist(sso_allowed_origins)

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
    identity_capture_service = authorize(IDENTITY_CAPTURE_ROLES)
    simulated_user = authorize(frozenset({"simulated_user"}))
    mfa_facilitator = authorize(frozenset({"facilitator"}))

    def execute(operation):
        try:
            return operation()
        except (
            ControllerError,
            ActionContractError,
            ActionValidationError,
            IdentityAuditError,
            ValueError,
        ) as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail=str(exc)
            ) from exc

    def authorize_sso_request(request: Request) -> None:
        try:
            sso_origins.authorize(request)
        except OriginDeniedError as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
            ) from exc

    async def bounded_json(
        request: Request, *, maximum: int, description: str
    ) -> dict[str, Any]:
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                declared_length = int(content_length)
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="invalid content length",
                ) from exc
            if declared_length < 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="invalid content length",
                )
            if declared_length > maximum:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"{description} payload is too large",
                )
        body = await request.body()
        if len(body) > maximum:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"{description} payload is too large",
            )
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="request body must be valid JSON",
            ) from exc
        if not isinstance(payload, dict):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="request body must be a JSON object",
            )
        return payload

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "component": "netstrike-portal"}

    @app.get("/participant", include_in_schema=False)
    def participant_page() -> FileResponse:
        return FileResponse(static_root / "participant.html")

    @app.get("/facilitator", include_in_schema=False)
    def facilitator_page() -> FileResponse:
        return FileResponse(static_root / "facilitator.html")

    @app.get("/sso", include_in_schema=False)
    def sso_page(request: Request) -> FileResponse:
        authorize_sso_request(request)
        return FileResponse(static_root / "sso.html")

    @app.get("/api/sso/state")
    def sso_state(request: Request) -> dict[str, Any]:
        authorize_sso_request(request)
        return service.sso_state()

    @app.post("/api/sso/sign-in")
    async def sso_sign_in(request: Request) -> dict[str, Any]:
        authorize_sso_request(request)
        payload = await bounded_json(
            request, maximum=MAX_SSO_REQUEST_BYTES, description="SSO sign-in"
        )
        if set(payload) != {"username", "credential"}:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="sign-in fields are invalid",
            )
        try:
            return service.sso_sign_in(
                payload.get("username"), payload.get("credential")
            )
        except SsoBoundaryError as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
            ) from exc
        except SsoExperienceError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail=str(exc)
            ) from exc

    @app.post("/api/sso/mfa")
    async def sso_mfa(request: Request) -> dict[str, Any]:
        authorize_sso_request(request)
        payload = await bounded_json(
            request, maximum=MAX_SSO_REQUEST_BYTES, description="SSO MFA"
        )
        if set(payload) != {"challenge_id", "decision"}:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="MFA decision fields are invalid",
            )
        try:
            return service.sso_decide_mfa(
                payload.get("challenge_id"), payload.get("decision")
            )
        except SsoExperienceError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail=str(exc)
            ) from exc

    @app.post("/api/sso/review-sessions")
    def sso_review_sessions(request: Request) -> dict[str, Any]:
        authorize_sso_request(request)
        try:
            return service.sso_review_sessions()
        except SsoExperienceError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail=str(exc)
            ) from exc

    @app.post("/api/sso/scheduled-mfa")
    async def scheduled_mfa_decision(
        request: Request,
        principal: PortalPrincipal = Depends(simulated_user),
    ) -> dict[str, Any]:
        authorize_sso_request(request)
        payload = await bounded_json(request, maximum=MAX_SSO_REQUEST_BYTES,
                                     description="scheduled MFA decision")
        if set(payload) != {"challenge_id", "decision"}:
            raise HTTPException(status_code=422, detail="MFA decision fields are invalid")
        return execute(lambda: service.decide_scheduled_mfa(
            principal, payload["challenge_id"], payload["decision"],
        ))

    @app.post("/api/facilitator/mfa/decision")
    def facilitator_mfa_decision(
        decision: MfaDecisionInput,
        principal: PortalPrincipal = Depends(mfa_facilitator),
    ) -> dict[str, Any]:
        return execute(lambda: service.decide_scheduled_mfa(
            principal, decision.challenge_id, decision.decision,
        ))

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

    @app.post("/api/services/identity/interactions")
    async def capture_identity_interaction(
        request: Request,
        principal: PortalPrincipal = Depends(identity_capture_service),
    ) -> dict[str, Any]:
        """Accept a bounded payload without reflecting credential-like input."""

        payload = await bounded_json(
            request,
            maximum=MAX_IDENTITY_CAPTURE_BYTES,
            description="identity interaction",
        )
        return execute(
            lambda: service.capture_identity_interaction(
                principal.actor_id, payload
            )
        )

    @app.get("/api/facilitator/state")
    def facilitator_state(
        _principal: PortalPrincipal = Depends(facilitator),
    ) -> dict[str, Any]:
        return service.facilitator_state()

    @app.get("/api/facilitator/identity-audit")
    def identity_audit(
        _principal: PortalPrincipal = Depends(facilitator),
    ) -> list[dict[str, Any]]:
        return service.identity_timeline()

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
            lambda: service.reset_run(new_run_id=request.new_run_id)
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
    audit_key = os.getenv("NETSTRIKE_IDENTITY_AUDIT_KEY")
    if not audit_key or len(audit_key.encode("utf-8")) < 32:
        raise ValueError(
            "NETSTRIKE_IDENTITY_AUDIT_KEY must contain at least 32 bytes"
        )
    raw_origins = os.getenv("NETSTRIKE_SSO_ALLOWED_ORIGINS")
    if not raw_origins:
        raise ValueError("NETSTRIKE_SSO_ALLOWED_ORIGINS must be configured")
    try:
        allowed_origins = json.loads(raw_origins)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "NETSTRIKE_SSO_ALLOWED_ORIGINS must be a JSON array"
        ) from exc
    if not isinstance(allowed_origins, list) or not all(
        isinstance(item, str) for item in allowed_origins
    ):
        raise ValueError("NETSTRIKE_SSO_ALLOWED_ORIGINS must be a JSON array")
    store = PortalStore(database_path)
    service = PortalService(
        store,
        run_id=run_id,
        identity_audit_key=audit_key.encode("utf-8"),
    )
    return create_app(
        service,
        TokenAuthenticator.from_environment(),
        sso_allowed_origins=allowed_origins,
    )
