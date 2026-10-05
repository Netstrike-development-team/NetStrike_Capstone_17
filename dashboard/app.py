"""Authenticated FastAPI surface for participants and exercise staff."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, Iterable

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError

from orchestrator.controller import ControllerError
from orchestrator.aar import RATINGS, build_report, render_markdown
from orchestrator.evidence import render_csv, render_jsonl
from shared.actions import ActionContractError, ActionExecutionError, ActionValidationError

from .auth import (
    PortalAuthenticationError,
    PortalAuthorizationError,
    PortalPrincipal,
    TokenAuthenticator,
)
from .identity_audit import IdentityAuditError
from .support import SupportEvidenceError
from .origin import OriginAllowlist, OriginDeniedError
from .service import PortalService
from .sso import SsoBoundaryError, SsoExperienceError
from .store import PortalStore
from .configuration import PortalConfiguration


PARTICIPANT_ROLES = frozenset(
    {
        "incident_lead",
        "soc_analyst",
        "identity_responder",
        "endpoint_responder",
        "cloud_responder",
    }
)
FACILITATOR_ROLES = frozenset({"facilitator", "technical_operator"})
IDENTITY_CAPTURE_ROLES = frozenset({"identity_capture_service"})
MAX_IDENTITY_CAPTURE_BYTES = 16 * 1024
MAX_SSO_REQUEST_BYTES = 4 * 1024
MAX_SUPPORT_BYTES = 20 * 1024


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


class SupportRequestInput(StrictInput):
    run_id: str = Field(min_length=1, max_length=128)
    idempotency_key: str = Field(min_length=1, max_length=128)
    objective_id: str = Field(pattern="^LO[1-5]$")
    message: str = Field(min_length=1, max_length=1024, pattern=r"\S")


class SupportReplyInput(StrictInput):
    run_id: str = Field(min_length=1, max_length=128)
    request_id: str = Field(min_length=1, max_length=128)
    idempotency_key: str = Field(min_length=1, max_length=128)
    kind: str = Field(pattern="^(hint|clarification|platform_issue)$")
    message: str = Field(min_length=1, max_length=1024, pattern=r"\S")
    objective_ids: list[Annotated[str, Field(pattern="^LO[1-5]$")]] = Field(min_length=1, max_length=5)


async def support_input(request: Request, model):
    """Bound streamed JSON before parsing; errors never echo private free text."""
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_SUPPORT_BYTES:
            raise HTTPException(status_code=413, detail="support payload is too large")
        body.extend(chunk)
    try:
        return model.model_validate_json(bytes(body))
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail="invalid support payload fields") from exc


class CloudAssessmentInput(StrictInput):
    principal_id: str = Field(min_length=1, max_length=128)
    confirmed_count: int = Field(ge=0, le=25, strict=True)
    conclusion: str = Field(pattern="^(mock_access_only|external_transfer_proven|unknown)$")
    evidence_ids: list[Annotated[str, Field(min_length=1, max_length=128)]] = Field(
        min_length=1, max_length=20,
    )


class RecoveryActionInput(StrictInput):
    action_id: str = Field(pattern=r"^(recovery\.fixture\.restore|recovery\.health\.validate)$")
    fixture_id: str = Field(min_length=1, max_length=128)
    key: str = Field(min_length=1, max_length=128)
    dry_run: bool = Field(default=True, strict=True)


BriefText = Annotated[str, Field(min_length=1, max_length=1024, pattern=r"\S")]
BriefEvidence = Annotated[str, Field(min_length=1, max_length=128)]


class RecoveryBriefInput(StrictInput):
    confirmed_scope: BriefText
    confirmed_cloud_records: int = Field(ge=0, le=25, strict=True)
    business_impact: BriefText
    actions_taken: BriefText
    remaining_risk: BriefText
    recommendations: list[BriefText] = Field(min_length=2, max_length=5)
    evidence_ids: list[BriefEvidence] = Field(min_length=1, max_length=20)


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


class ArchiveInput(StrictInput):
    run_id: str = Field(min_length=1, max_length=128)
    expected_bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class MfaDecisionInput(StrictInput):
    challenge_id: str = Field(min_length=1, max_length=128)
    decision: str = Field(pattern="^(approve|deny)$")


class ImprovementInput(StrictInput):
    description: BriefText
    owner: Annotated[str, Field(min_length=1, max_length=128, pattern=r"\S")]
    priority: str = Field(pattern="^(high|medium|low)$")
    target_date: Annotated[str, Field(min_length=1, max_length=128, pattern=r"\S")]


class ObjectiveJudgmentInput(StrictInput):
    run_id: str = Field(min_length=1, max_length=128)
    objective_id: str = Field(pattern="^LO[1-5]$")
    rating: str = Field(pattern="^(" + "|".join(RATINGS) + ")$")
    rationale: Annotated[str, Field(min_length=1, max_length=2048, pattern=r"\S")]
    evidence_ids: list[BriefEvidence] = Field(default_factory=list, max_length=20)
    expected_revision: int = Field(ge=0, strict=True)
    override_reason: str = Field(default="", max_length=2048)
    platform_reason: str = Field(default="", max_length=2048)
    improvement_actions: list[ImprovementInput] = Field(
        default_factory=list, max_length=5
    )


class TimelineEntryInput(StrictInput):
    occurred_at: AwareDatetime
    statement_type: str = Field(pattern="^(fact|inference)$")
    event_id: BriefEvidence
    summary: Annotated[str, Field(min_length=1, max_length=512, pattern=r"\S")]


class TimelineInput(StrictInput):
    run_id: str = Field(min_length=1, max_length=128)
    entries: list[TimelineEntryInput] = Field(min_length=6, max_length=12)


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
        service.clock.attach()
        shutdown = asyncio.Event()

        async def drive_clock() -> None:
            try:
                while not shutdown.is_set():
                    try:
                        await asyncio.wait_for(shutdown.wait(), timeout=1)
                        break
                    except asyncio.TimeoutError:
                        pass
                    # Synchronous handlers must not block the ASGI loop. Drain an
                    # in-flight worker even on cancellation; never orphan old-run work.
                    work = asyncio.create_task(asyncio.to_thread(service.clock.tick))
                    try:
                        await asyncio.shield(work)
                    except asyncio.CancelledError:
                        await work
                        raise
            except (Exception, asyncio.CancelledError):
                await asyncio.to_thread(service.clock.fault, "driver_failed")
                raise

        clock_task = asyncio.create_task(drive_clock(), name="netstrike-exercise-clock")
        try:
            yield
        finally:
            shutdown.set()
            try:
                try:
                    await asyncio.shield(clock_task)
                except asyncio.CancelledError:
                    await clock_task
                    raise
            finally:
                # Driver work has finished before any shutdown safety transition.
                await asyncio.to_thread(service.clock.detach)

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
        if request.url.path.startswith("/api/evaluator/"):
            response.headers["Cache-Control"] = "no-store"
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
    evaluator = authorize(frozenset({"evaluator", "facilitator"}))
    support_observer = authorize(frozenset({"evaluator", "facilitator", "technical_operator"}))

    def execute(operation):
        try:
            return operation()
        except SupportEvidenceError as exc:
            # Distinguish possibly committed support writes from definite conflicts.
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
            ) from exc
        except (
            ControllerError,
            ActionContractError,
            ActionExecutionError,
            ActionValidationError,
            IdentityAuditError,
            ValueError,
        ) as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail=str(exc)
            ) from exc

    def scoped_control(request: Request, operation):
        """Optional legacy-compatible run header; check and operate under one lock."""
        supplied = request.headers.getlist("X-Exercise-Run-ID")
        if len(supplied) > 1:
            raise HTTPException(status_code=422, detail="ambiguous exercise run header")
        expected_run = supplied[0] if supplied else None
        if expected_run is not None and (
            not 1 <= len(expected_run) <= 128 or expected_run.strip() != expected_run
            or any(ord(char) < 32 for char in expected_run)
        ):
            raise HTTPException(status_code=422, detail="invalid exercise run header")
        with service.run.state_lock:
            if expected_run is not None and expected_run != service.run.run_id:
                raise HTTPException(
                    status_code=409, detail="run changed; refresh before acting or exporting"
                )
            return execute(operation)

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

    @app.get("/evidence", include_in_schema=False)
    def evidence_page() -> FileResponse:
        return FileResponse(static_root / "evidence.html")

    @app.get("/evaluator", include_in_schema=False)
    def evaluator_page() -> FileResponse:
        return FileResponse(static_root / "evaluator.html")

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
        request: Request,
        decision: MfaDecisionInput,
        principal: PortalPrincipal = Depends(mfa_facilitator),
    ) -> dict[str, Any]:
        return scoped_control(request, lambda: service.decide_scheduled_mfa(
            principal, decision.challenge_id, decision.decision,
        ))

    @app.get("/api/participant/state")
    def participant_state(
        _principal: PortalPrincipal = Depends(participant),
    ) -> dict[str, Any]:
        return service.participant_state()

    @app.get("/api/participant/evidence")
    def participant_evidence(
        principal: PortalPrincipal = Depends(participant),
        after_sequence: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=100),
    ) -> dict[str, Any]:
        return service.participant_evidence(
            principal, after_sequence=after_sequence, limit=limit,
        )

    @app.get("/api/participant/directory")
    def participant_directory(
        _principal: PortalPrincipal = Depends(participant),
    ) -> list[dict[str, Any]]:
        return service.participant_directory()

    @app.get("/api/participant/support")
    def participant_support(response: Response, principal: PortalPrincipal = Depends(participant)):
        response.headers["Cache-Control"] = "no-store"
        return execute(lambda: service.support.view(principal))

    @app.post("/api/participant/support")
    async def request_support(request: Request, principal: PortalPrincipal = Depends(participant)):
        payload = await support_input(request, SupportRequestInput)
        return await asyncio.to_thread(
            execute, lambda: service.support.request(principal, **payload.model_dump())
        )

    @app.get("/api/facilitator/support")
    def staff_support(response: Response, principal: PortalPrincipal = Depends(support_observer)):
        response.headers["Cache-Control"] = "no-store"
        return execute(lambda: service.support.view(principal, staff=True))

    @app.post("/api/facilitator/support/replies")
    async def reply_support(request: Request, principal: PortalPrincipal = Depends(facilitator)):
        payload = await support_input(request, SupportReplyInput)
        return await asyncio.to_thread(
            execute, lambda: service.support.respond(principal, **payload.model_dump())
        )

    @app.post("/api/participant/actions")
    def participant_action(
        payload: ActionInput,
        request: Request,
        principal: PortalPrincipal = Depends(participant),
    ) -> dict[str, Any]:
        result = scoped_control(request,
            lambda: service.submit_action(
                principal,
                action_id=payload.action_id,
                target_type=payload.target_type,
                target_id=payload.target_id,
                idempotency_key=payload.idempotency_key,
                parameters=payload.parameters,
                dry_run=payload.dry_run,
            )
        )
        if not result["successful"]:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=result)
        return result

    @app.post("/api/participant/checkpoints/dp1")
    def submit_dp1(
        payload: Dp1Input,
        request: Request,
        principal: PortalPrincipal = Depends(participant),
    ) -> dict[str, Any]:
        return scoped_control(request,
            lambda: service.submit_dp1(
                principal,
                affected_identity=payload.affected_identity,
                classification=payload.classification,
                evidence=tuple(
                    (item.reference_id, item.source) for item in payload.evidence
                ),
            )
        )

    @app.post("/api/participant/timeline")
    def submit_timeline(
        payload: TimelineInput,
        request: Request,
        principal: PortalPrincipal = Depends(participant),
    ):
        return scoped_control(request,
            lambda: service.submit_timeline(
                principal,
                **payload.model_dump(mode="json"),
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

    @app.get("/api/participant/cloud")
    def cloud_view(_principal: PortalPrincipal = Depends(participant)):
        return execute(service.cloud_view)

    @app.post("/api/participant/cloud/assessment")
    def cloud_assessment(
        payload: CloudAssessmentInput,
        request: Request,
        principal: PortalPrincipal = Depends(participant),
    ):
        return scoped_control(request, lambda: service.submit_cloud_assessment(
            principal, **payload.model_dump(),
        ))

    @app.get("/api/facilitator/state")
    def facilitator_state(
        response: Response,
        principal: PortalPrincipal = Depends(facilitator),
    ) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        return {**service.facilitator_state(), "principal_role": principal.role}

    @app.get("/api/evaluator/report")
    def aar_report(request: Request, _principal: PortalPrincipal = Depends(evaluator)):
        return scoped_control(request, service.aar_report)

    @app.post("/api/evaluator/judgments")
    def objective_judgment(
        request: ObjectiveJudgmentInput,
        principal: PortalPrincipal = Depends(evaluator),
    ):
        return execute(
            lambda: service.judge_objective(
                principal,
                request.model_dump(exclude={"run_id"}),
                run_id=request.run_id,
            )
        )

    def review_export(request: Request, *, markdown: bool):
        """Check optional snapshot identity and serialize within the run lock."""
        supplied = request.headers.getlist("X-Review-Bundle-SHA256")
        if len(supplied) > 1:
            raise HTTPException(status_code=422, detail="ambiguous review snapshot header")
        expected = supplied[0] if supplied else None
        if expected is not None and (
            len(expected) != 64 or any(char not in "0123456789abcdef" for char in expected)
        ):
            raise HTTPException(status_code=422, detail="invalid review snapshot header")
        bundle = service.aar_bundle()
        if expected is not None and expected != bundle["content_sha256"]:
            raise HTTPException(status_code=409, detail="review changed; refresh before exporting")
        headers = {"Cache-Control": "no-store"}
        if markdown:
            headers["Content-Disposition"] = 'attachment; filename="after-action-review.md"'
            return Response(render_markdown(build_report(bundle)), media_type="text/markdown",
                            headers=headers)
        return JSONResponse(bundle, headers=headers)

    @app.get("/api/evaluator/exports/bundle.json")
    def aar_bundle(request: Request, _principal: PortalPrincipal = Depends(evaluator)):
        return scoped_control(request, lambda: review_export(request, markdown=False))

    @app.get("/api/evaluator/exports/aar.md")
    def aar_markdown(request: Request, _principal: PortalPrincipal = Depends(evaluator)):
        return scoped_control(request, lambda: review_export(request, markdown=True))

    @app.get("/api/participant/feedback")
    def learner_feedback(_principal: PortalPrincipal = Depends(participant)):
        return execute(service.participant_feedback)

    @app.post("/api/evaluator/archives")
    def capture_archive(request: ArchiveInput, principal: PortalPrincipal = Depends(evaluator)):
        return execute(lambda: service.capture_review_archive(principal, **request.model_dump()))

    @app.get("/api/evaluator/archives")
    def list_archives(response: Response, _principal: PortalPrincipal = Depends(evaluator),
                      after_sequence: int = Query(default=0, ge=0),
                      limit: int = Query(default=50, ge=1, le=100)):
        response.headers["Cache-Control"] = "no-store"
        return execute(lambda: service.review_archives(after_sequence=after_sequence, limit=limit))

    def archived(identifier: str) -> dict:
        snapshot = execute(lambda: service.review_archive(identifier))
        if snapshot is None:
            raise HTTPException(status_code=404, detail="review archive not found")
        return snapshot

    @app.get("/api/evaluator/archives/{identifier}/bundle.json")
    def archived_bundle(identifier: str, response: Response,
                        _principal: PortalPrincipal = Depends(evaluator)):
        response.headers["Cache-Control"] = "no-store"
        return archived(identifier)["bundle"]

    @app.get("/api/evaluator/archives/{identifier}/report")
    def archived_report(identifier: str, response: Response,
                        _principal: PortalPrincipal = Depends(evaluator)):
        response.headers["Cache-Control"] = "no-store"
        return archived(identifier)["report"]

    @app.get("/api/evaluator/archives/{identifier}/aar.md")
    def archived_markdown(identifier: str, _principal: PortalPrincipal = Depends(evaluator)):
        return Response(render_markdown(archived(identifier)["report"]), media_type="text/markdown",
                        headers={"Cache-Control": "no-store", "Content-Disposition":
                                 'attachment; filename="archived-after-action-review.md"'})

    @app.get("/api/evaluator/archives/{identifier}/events.jsonl")
    def archived_events(identifier: str, _principal: PortalPrincipal = Depends(evaluator)):
        return Response(render_jsonl(archived(identifier)["bundle"]["events"]),
                        media_type="application/x-ndjson", headers={"Cache-Control": "no-store",
                        "Content-Disposition": 'attachment; filename="archived-events.jsonl"'})

    @app.get("/api/participant/recovery")
    def impact_view(_principal: PortalPrincipal = Depends(participant)):
        return execute(service.impact_view)

    @app.post("/api/participant/recovery/action")
    def recover_fixture(
        payload: RecoveryActionInput,
        request: Request,
        principal: PortalPrincipal = Depends(participant),
    ):
        result = scoped_control(
            request, lambda: service.recover_fixture(principal, **payload.model_dump())
        )
        if not result["successful"]:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=result)
        return result

    @app.post("/api/participant/recovery/brief")
    def recovery_brief(
        payload: RecoveryBriefInput,
        request: Request,
        principal: PortalPrincipal = Depends(participant),
    ):
        return scoped_control(
            request, lambda: service.submit_recovery_brief(principal, payload.model_dump())
        )

    @app.get("/api/facilitator/identity-audit")
    def identity_audit(
        _principal: PortalPrincipal = Depends(facilitator),
    ) -> list[dict[str, Any]]:
        return service.identity_timeline()

    @app.post("/api/facilitator/prepare")
    def prepare(
        request: Request,
        principal: PortalPrincipal = Depends(facilitator),
    ) -> dict[str, Any]:
        return scoped_control(request, lambda: service.prepare_run(principal))

    @app.post("/api/facilitator/start")
    def start(
        request: Request,
        principal: PortalPrincipal = Depends(facilitator),
    ) -> dict[str, Any]:
        return scoped_control(request, lambda: service.start_run(principal))

    @app.get("/api/facilitator/readiness")
    def readiness(response: Response, _principal: PortalPrincipal = Depends(facilitator)) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        return service.readiness()

    @app.get("/api/facilitator/clock")
    def clock_health(response: Response, _principal: PortalPrincipal = Depends(facilitator)):
        response.headers["Cache-Control"] = "no-store"
        return service.clock.snapshot()

    @app.post("/api/facilitator/pause")
    def pause(
        request: Request,
        _principal: PortalPrincipal = Depends(facilitator),
    ) -> dict[str, Any]:
        return scoped_control(request, lambda: service.control_run("pause"))

    @app.post("/api/facilitator/resume")
    def resume(
        request: Request,
        _principal: PortalPrincipal = Depends(facilitator),
    ) -> dict[str, Any]:
        return scoped_control(request, lambda: service.control_run("resume"))

    @app.post("/api/facilitator/advance")
    def advance(
        request: AdvanceInput,
        http_request: Request,
        _principal: PortalPrincipal = Depends(facilitator),
    ) -> dict[str, Any]:
        return scoped_control(http_request, lambda: service.control_run("advance", request.elapsed_seconds))

    @app.post("/api/facilitator/deliver")
    def deliver(
        request: ItemInput,
        http_request: Request,
        _principal: PortalPrincipal = Depends(facilitator),
    ) -> dict[str, Any]:
        return scoped_control(http_request, lambda: service.control_run("deliver", request.item_id))

    @app.post("/api/facilitator/skip")
    def skip(
        request: SkipInput,
        http_request: Request,
        _principal: PortalPrincipal = Depends(facilitator),
    ) -> dict[str, Any]:
        return scoped_control(http_request, lambda: service.control_run("skip", request.item_id, request.reason))

    @app.post("/api/facilitator/checkpoints/dp2")
    def resolve_dp2(
        request: Request,
        _principal: PortalPrincipal = Depends(facilitator),
    ) -> dict[str, Any]:
        return scoped_control(request,
            lambda: {
                "evaluation": PortalService.evaluation_dict(
                    service.resolve_dp2()
                ),
                "state": service.facilitator_state(),
            }
        )

    @app.post("/api/facilitator/stop")
    def stop(
        request: StopInput,
        http_request: Request,
        principal: PortalPrincipal = Depends(facilitator),
    ) -> dict[str, Any]:
        return scoped_control(http_request, lambda: service.stop_run(request.reason, principal))

    @app.post("/api/facilitator/checkpoints/dp3")
    def resolve_dp3(request: Request, _principal: PortalPrincipal = Depends(facilitator)):
        return scoped_control(request, lambda: {
            "evaluation": PortalService.evaluation_dict(service.resolve_cloud()),
            "state": service.facilitator_state(),
        })

    @app.post("/api/facilitator/reset")
    def reset(
        request: ResetInput,
        http_request: Request,
        principal: PortalPrincipal = Depends(facilitator),
    ) -> dict[str, Any]:
        return scoped_control(http_request,
            lambda: service.reset_run(new_run_id=request.new_run_id, principal=principal)
        )

    @app.post("/api/facilitator/checkpoints/dp4")
    def resolve_dp4(request: Request, _principal: PortalPrincipal = Depends(facilitator)):
        return scoped_control(request, lambda: {
            "evaluation": PortalService.evaluation_dict(service.resolve_impact()),
            "state": service.facilitator_state(),
        })

    @app.post("/api/facilitator/impact/rollback")
    def rollback_impact(request: Request, principal: PortalPrincipal = Depends(facilitator)):
        return scoped_control(request, lambda: service.rollback_impact(principal))

    def current_events() -> list[dict[str, Any]]:
        return service.store.events(
            service.run.definition.exercise_id, service.run.run_id
        )

    @app.get("/api/facilitator/exports/events.jsonl")
    def export_events_jsonl(
        request: Request,
        _principal: PortalPrincipal = Depends(facilitator),
    ) -> Response:
        return scoped_control(request, lambda: Response(
            content=render_jsonl(current_events()), media_type="application/x-ndjson",
            headers={"Cache-Control": "no-store", "Content-Disposition":
                     f'attachment; filename="{service.run.run_id}-events.jsonl"'},
        ))

    @app.get("/api/facilitator/exports/events.csv")
    def export_events_csv(
        request: Request,
        _principal: PortalPrincipal = Depends(facilitator),
    ) -> Response:
        return scoped_control(request, lambda: Response(
            content=render_csv(current_events()), media_type="text/csv",
            headers={"Cache-Control": "no-store", "Content-Disposition":
                     f'attachment; filename="{service.run.run_id}-events.csv"'},
        ))

    return app


def create_default_app() -> FastAPI:
    """Create the production app from runtime-injected offline configuration."""

    configuration = PortalConfiguration.from_environment()
    store = PortalStore(configuration.database)
    try:
        service = PortalService(
            store, run_id=configuration.run_id, profile_path=configuration.profile_path,
            scenario_path=configuration.scenario_path, impact_root=configuration.impact_root,
            identity_audit_key=configuration.audit_key,
        )
        return create_app(service, configuration.authenticator,
                          sso_allowed_origins=configuration.origins)
    except Exception:
        store.close()  # Never delete partially constructed state or retained evidence.
        raise
