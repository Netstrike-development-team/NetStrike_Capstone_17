"""SQLite persistence for events and participant submissions."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from shared.events import EventValidator, redact_sensitive


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

    def close(self) -> None:
        """Close the SQLite connection."""

        with self._lock:
            self._connection.close()
