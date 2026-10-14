"""SQLite persistence for events, submissions, and identity audit records."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from shared.events import EventValidator, redact_sensitive
from .archive import MAX_BYTES, archive_id, encode_bundle, metadata, validate_snapshot


class PortalStore:
    """Small thread-safe persistence layer for the single-team MVP."""

    def __init__(self, path: Path | str = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._validator = EventValidator()
        self._initialize()

    def _initialize(self) -> None:
        with self._lock, self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY,
                    exercise_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    visibility TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    UNIQUE(exercise_id, run_id, sequence)
                );
                CREATE INDEX IF NOT EXISTS events_run_sequence
                    ON events(exercise_id, run_id, sequence);
                CREATE TABLE IF NOT EXISTS submissions (
                    submission_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    exercise_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    submission_type TEXT NOT NULL,
                    submitted_at TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    result TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS identity_audit (
                    audit_id TEXT PRIMARY KEY,
                    event_id TEXT NOT NULL UNIQUE,
                    exercise_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    synthetic_identity TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    action TEXT NOT NULL,
                    result TEXT NOT NULL,
                    source_service TEXT NOT NULL,
                    source_event_id TEXT NOT NULL,
                    credential_kind TEXT,
                    submission_reference TEXT,
                    UNIQUE(exercise_id, run_id, source_service, source_event_id),
                    FOREIGN KEY(event_id) REFERENCES events(event_id)
                );
                CREATE INDEX IF NOT EXISTS identity_audit_timeline
                    ON identity_audit(
                        exercise_id, run_id, occurred_at, audit_id
                    );
                CREATE TABLE IF NOT EXISTS review_archives (
                    archive_sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    archive_id TEXT NOT NULL UNIQUE,
                    exercise_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    bundle_sha256 TEXT NOT NULL,
                    audit_event_id TEXT NOT NULL UNIQUE,
                    metadata TEXT NOT NULL,
                    bundle TEXT NOT NULL,
                    UNIQUE(exercise_id, run_id, bundle_sha256)
                );
                CREATE INDEX IF NOT EXISTS review_archives_exercise_sequence
                    ON review_archives(exercise_id, archive_sequence);
                CREATE TRIGGER IF NOT EXISTS review_archives_no_update
                BEFORE UPDATE ON review_archives BEGIN
                    SELECT RAISE(ABORT, 'review archives are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS review_archives_no_delete
                BEFORE DELETE ON review_archives BEGIN
                    SELECT RAISE(ABORT, 'review archives are immutable');
                END;
                """
            )

    def append_event(self, event: Mapping[str, Any]) -> dict[str, Any]:
        """Validate, redact, and persist one immutable event."""

        sanitized = redact_sensitive(dict(event))
        self._validator.validate(sanitized)
        payload = json.dumps(sanitized, sort_keys=True, separators=(",", ":"))
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO events(
                    event_id, exercise_id, run_id, sequence, visibility, payload
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    sanitized["event_id"],
                    sanitized["exercise_id"],
                    sanitized["run_id"],
                    sanitized["sequence"],
                    sanitized["visibility"],
                    payload,
                ),
            )
        return sanitized

    def events(
        self,
        exercise_id: str,
        run_id: str,
        *,
        visibilities: frozenset[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Return events in run sequence order with optional visibility filtering."""

        query = "SELECT payload FROM events WHERE exercise_id = ? AND run_id = ?"
        parameters: list[Any] = [exercise_id, run_id]
        if visibilities:
            placeholders = ",".join("?" for _ in visibilities)
            query += f" AND visibility IN ({placeholders})"
            parameters.extend(sorted(visibilities))
        query += " ORDER BY sequence"
        with self._lock:
            rows = self._connection.execute(query, parameters).fetchall()
        return [json.loads(row["payload"]) for row in rows]

    # Submission identity and correlation fields remain explicit for audit.
    # pylint: disable=too-many-arguments
    def save_submission(
        self,
        *,
        exercise_id: str,
        run_id: str,
        actor_id: str,
        submission_type: str,
        payload: Mapping[str, Any],
        result: Mapping[str, Any],
    ) -> int:
        """Persist a redacted participant submission and its evaluation result."""

        submitted_at = (
            datetime.now(timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )
        with self._lock, self._connection:
            cursor = self._connection.execute(
                """
                INSERT INTO submissions(
                    exercise_id, run_id, actor_id, submission_type,
                    submitted_at, payload, result
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    exercise_id,
                    run_id,
                    actor_id,
                    submission_type,
                    submitted_at,
                    json.dumps(redact_sensitive(dict(payload)), sort_keys=True),
                    json.dumps(redact_sensitive(dict(result)), sort_keys=True),
                ),
            )
            return int(cursor.lastrowid)

    def submissions(self, run_id: str) -> list[dict[str, Any]]:
        """Return facilitator-visible submissions for one run."""

        with self._lock:
            rows = self._connection.execute(
                """
                SELECT submission_id, actor_id, submission_type, submitted_at,
                       payload, result
                FROM submissions WHERE run_id = ? ORDER BY submission_id
                """,
                (run_id,),
            ).fetchall()
        return [
            {
                "submission_id": row["submission_id"],
                "actor_id": row["actor_id"],
                "submission_type": row["submission_type"],
                "submitted_at": row["submitted_at"],
                "payload": json.loads(row["payload"]),
                "result": json.loads(row["result"]),
            }
            for row in rows
        ]

    def append_identity_audit(
        self,
        event: Mapping[str, Any],
        record: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Atomically persist a canonical event and its safe audit projection."""

        sanitized_event = redact_sensitive(dict(event))
        self._validator.validate(sanitized_event)
        event_payload = json.dumps(
            sanitized_event, sort_keys=True, separators=(",", ":")
        )
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO events(
                    event_id, exercise_id, run_id, sequence, visibility, payload
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    sanitized_event["event_id"],
                    sanitized_event["exercise_id"],
                    sanitized_event["run_id"],
                    sanitized_event["sequence"],
                    sanitized_event["visibility"],
                    event_payload,
                ),
            )
            self._connection.execute(
                """
                INSERT INTO identity_audit(
                    audit_id, event_id, exercise_id, run_id, phase,
                    synthetic_identity, occurred_at, action, result,
                    source_service, source_event_id, credential_kind,
                    submission_reference
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["audit_id"],
                    sanitized_event["event_id"],
                    record["exercise_id"],
                    record["run_id"],
                    record["phase"],
                    record["synthetic_identity"],
                    record["occurred_at"],
                    record["action"],
                    record["result"],
                    record["source_service"],
                    record["source_event_id"],
                    record.get("credential_kind"),
                    record.get("submission_reference"),
                ),
            )
        return self._identity_audit_result(record, sanitized_event["provenance"])

    @staticmethod
    def _identity_audit_result(
        row: Mapping[str, Any], provenance: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Normalize SQLite or input mappings into the public audit shape."""

        return {
            "audit_id": row["audit_id"],
            "event_id": row["event_id"],
            "exercise_id": row["exercise_id"],
            "run_id": row["run_id"],
            "phase": row["phase"],
            "synthetic_identity": row["synthetic_identity"],
            "occurred_at": row["occurred_at"],
            "action": row["action"],
            "result": row["result"],
            "source_service": row["source_service"],
            "source_event_id": row["source_event_id"],
            "credential_kind": row["credential_kind"],
            "submission_reference": row["submission_reference"],
            "provenance": dict(provenance),
        }

    def identity_audit(
        self, exercise_id: str, run_id: str
    ) -> list[dict[str, Any]]:
        """Return a run's identity evidence in occurrence order."""

        with self._lock:
            rows = self._connection.execute(
                """
                SELECT identity_audit.*, events.payload AS event_payload
                FROM identity_audit
                JOIN events ON events.event_id = identity_audit.event_id
                WHERE identity_audit.exercise_id = ?
                  AND identity_audit.run_id = ?
                ORDER BY occurred_at, events.sequence
                """,
                (exercise_id, run_id),
            ).fetchall()
        return [
            self._identity_audit_result(
                row, json.loads(row["event_payload"])["provenance"]
            )
            for row in rows
        ]

    def identity_audit_by_source(
        self,
        exercise_id: str,
        run_id: str,
        source_service: str,
        source_event_id: str,
    ) -> dict[str, Any] | None:
        """Look up an interaction by its source idempotency key."""

        with self._lock:
            row = self._connection.execute(
                """
                SELECT identity_audit.*, events.payload AS event_payload
                FROM identity_audit
                JOIN events ON events.event_id = identity_audit.event_id
                WHERE identity_audit.exercise_id = ?
                  AND identity_audit.run_id = ?
                  AND source_service = ? AND source_event_id = ?
                """,
                (exercise_id, run_id, source_service, source_event_id),
            ).fetchone()
        if row is None:
            return None
        event = json.loads(row["event_payload"])
        return self._identity_audit_result(row, event["provenance"])

    def delete_identity_audit(self, exercise_id: str, run_id: str) -> int:
        """Delete only the transient audit projection for one completed run."""

        with self._lock, self._connection:
            cursor = self._connection.execute(
                """
                DELETE FROM identity_audit
                WHERE exercise_id = ? AND run_id = ?
                """,
                (exercise_id, run_id),
            )
        return int(cursor.rowcount)

    def append_review_archive(self, bundle: dict, audit: dict) -> dict:
        """Commit the frozen snapshot and its canonical audit as one transaction."""
        encoded = encode_bundle(bundle)
        record = metadata(bundle, audit)
        event_payload = json.dumps(audit, sort_keys=True, separators=(",", ":"))
        with self._lock, self._connection:
            self._connection.execute(
                """INSERT INTO review_archives(
                    archive_id, exercise_id, run_id, bundle_sha256, audit_event_id, metadata, bundle
                ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (record["archive_id"], record["exercise_id"], record["run_id"],
                 record["bundle_sha256"], record["audit_event_id"], json.dumps(record, sort_keys=True), encoded),
            )
            self._connection.execute(
                """INSERT INTO events(event_id, exercise_id, run_id, sequence, visibility, payload)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (audit["event_id"], audit["exercise_id"], audit["run_id"], audit["sequence"],
                 audit["visibility"], event_payload),
            )
        return record

    def _review_snapshot(self, row) -> dict:
        if len(row["bundle"].encode("utf-8")) > MAX_BYTES:
            raise ValueError("review archive exceeds the offline review limit")
        record = json.loads(row["metadata"])
        bundle = json.loads(row["bundle"])
        with self._lock:
            event = self._connection.execute(
                "SELECT payload FROM events WHERE event_id = ?", (row["audit_event_id"],)
            ).fetchone()
        if event is None:
            raise ValueError("review archive audit is missing")
        report = validate_snapshot(record, bundle, json.loads(event["payload"]))
        if any(row[key] != record[key] for key in (
            "archive_id", "exercise_id", "run_id", "bundle_sha256", "audit_event_id",
        )):
            raise ValueError("review archive storage correlation is invalid")
        return {"metadata": {**record, "archive_sequence": row["archive_sequence"]},
                "bundle": bundle, "report": report}

    def review_archive(self, exercise_id: str, identifier: str) -> dict | None:
        """Retrieve only a validated, exercise-scoped immutable staff snapshot."""
        archive_id(identifier)
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM review_archives WHERE exercise_id = ? AND archive_id = ?",
                (exercise_id, identifier),
            ).fetchone()
        return self._review_snapshot(row) if row is not None else None

    def review_archive_by_hash(self, exercise_id: str, run_id: str, digest: str) -> dict | None:
        """Find an already-captured exact snapshot without creating a new audit."""
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM review_archives WHERE exercise_id = ? AND run_id = ? AND bundle_sha256 = ?",
                (exercise_id, run_id, digest),
            ).fetchone()
        return self._review_snapshot(row) if row is not None else None

    def review_archives(self, exercise_id: str, *, after_sequence: int = 0, limit: int = 50) -> dict:
        """Return a bounded metadata page; no old-run learner or evaluator prose."""
        if not isinstance(after_sequence, int) or isinstance(after_sequence, bool) or after_sequence < 0:
            raise ValueError("invalid review archive page")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
            raise ValueError("invalid review archive page")
        with self._lock:
            rows = self._connection.execute(
                """SELECT archive_id FROM review_archives WHERE exercise_id = ? AND archive_sequence > ?
                   ORDER BY archive_sequence LIMIT ?""", (exercise_id, after_sequence, limit + 1),
            ).fetchall()
        # Validate one bounded bundle at a time, not up to 101 large bundles in memory.
        page = []
        for row in rows[:limit]:
            snapshot = self.review_archive(exercise_id, row["archive_id"])
            if snapshot is None:
                raise ValueError("review archive changed during listing")
            page.append(snapshot["metadata"])
        return {"archives": page, "has_more": len(rows) > limit,
                "next_sequence": page[-1]["archive_sequence"] if page else after_sequence}

    def close(self) -> None:
        """Close the SQLite connection."""

        with self._lock:
            self._connection.close()
