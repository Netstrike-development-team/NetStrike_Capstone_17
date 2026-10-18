"""Bounded staff-batch to learner-audit publication; no network or ingestion claim."""

from __future__ import annotations

import argparse
import hashlib
import sys
import uuid
from pathlib import Path

from . import event_spool as staff
from .learner_audit import VERSION, project

MAX_SOURCE_BYTES = 32 * 1024 * 1024
MAX_SOURCE_EVENTS = 10000
MAX_SOURCE_BATCHES = 100


def _head(exercise, batches):
    return {"version": VERSION, "exercise_id": exercise,
            "batches": len(batches),
            "prefix_sha256": hashlib.sha256(staff._json([(name, receipt) for name, _content, receipt in batches])).hexdigest(),
            "events": sum(item["events"] for _name, _content, item in batches)}


def _source(root, exercise):
    if root.is_symlink() or not root.is_dir():
        raise staff.SpoolError("source spool unavailable")
    paths = staff._batch_paths(list(root.iterdir()))
    if len(paths) > MAX_SOURCE_BATCHES:
        raise staff.SpoolError("source batch limit exceeded")
    if sum((p / "events.jsonl").lstat().st_size for p in paths) > MAX_SOURCE_BYTES:
        raise staff.SpoolError("source byte limit exceeded")
    _state, initialized, manifests = staff._batches(root, exercise)
    if not initialized:
        raise staff.SpoolError("source checkpoint unavailable")
    rows = []
    sequences, identifiers = {}, set()
    for path, manifest in zip(paths, manifests, strict=True):
        content = staff._safe_file(path / "events.jsonl", staff.MAX_BATCH_BYTES)
        if hashlib.sha256(content).hexdigest() != manifest["events_sha256"]:
            raise staff.SpoolError("source batch changed")
        selected = []
        for raw in content.splitlines():
            if len(raw) > staff.MAX_EVENT_BYTES or len(identifiers) >= MAX_SOURCE_EVENTS:
                raise staff.SpoolError("source event limit exceeded")
            event = staff._load(raw)
            projected = project(event)
            if (event["exercise_id"] != exercise or event["event_id"] in identifiers
                    or event["sequence"] != sequences.get(event["run_id"], 0) + 1):
                raise staff.SpoolError("source correlation mismatch")
            identifiers.add(event["event_id"])
            sequences[event["run_id"]] = event["sequence"]
            if projected is not None:
                selected.append(staff._json(projected))
        payload = b"".join(selected)
        receipt = {"version": VERSION, "source_sha256": manifest["events_sha256"],
                   "projection_sha256": hashlib.sha256(payload).hexdigest(),
                   "events": len(selected)}
        rows.append((path.name, payload, receipt))
        if len(payload) > staff.MAX_BATCH_BYTES or sum(len(row[1]) for row in rows) > MAX_SOURCE_BYTES:
            raise staff.SpoolError("learner output limit exceeded")
    return rows


def _existing(root, exercise, rows):
    if not root.exists():
        if root.is_symlink():
            raise staff.SpoolError("linked learner spool")
        return 0, False
    staff._directory(root)
    entries = list(root.iterdir())
    paths = staff._batch_paths(entries)
    if not entries:
        return 0, False
    checkpoint = root / "HEAD.json"
    if not checkpoint.exists() and not checkpoint.is_symlink():
        if paths or any(p.name != ".lock" and not p.name.startswith(".head-") for p in entries):
            raise staff.SpoolError("missing learner checkpoint")
        return 0, False  # Initial HEAD-write interruption; private .head files only.
    head = staff._load(staff._safe_file(checkpoint, 16384))
    if (not isinstance(head, dict) or type(head.get("batches")) is not int
            or not 0 <= head["batches"] <= len(paths)
            or len(paths) > len(rows)):
        raise staff.SpoolError("invalid learner checkpoint")
    for index, path in enumerate(paths):
        name, content, receipt = rows[index]
        if (path.name != name or {p.name for p in path.iterdir()} != {"events.jsonl", "manifest.json"}
                or staff._safe_file(path / "events.jsonl", staff.MAX_BATCH_BYTES) != content
                or staff._load(staff._safe_file(path / "manifest.json", 4096)) != receipt):
            raise staff.SpoolError("learner history or source prefix changed")
    seen = head["batches"]
    if seen > len(paths) or head != _head(exercise, rows[:seen]):
        raise staff.SpoolError("learner checkpoint does not match retained history")
    return len(paths), True  # Adopt only fully verified commits after a HEAD crash.


def _publish(root, row):
    name, content, receipt = row
    stage = root / (".pending-" + uuid.uuid4().hex)
    stage.mkdir(mode=0o700)
    staff._write(stage / "events.jsonl", content)
    staff._write(stage / "manifest.json", staff._json(receipt))
    staff._sync(stage)
    destination = root / name
    if destination.exists() or destination.is_symlink():
        raise staff.SpoolError("learner batch already exists")
    stage.rename(destination)
    staff._sync(root)


def export(source_spool, output, *, exercise_id, limit=10, execute=False):
    """Inspect/replay immutable prefixes; publish only new reviewed projection batches."""
    if (not isinstance(exercise_id, str) or not 1 <= len(exercise_id) <= 128
            or type(limit) is not int or not 1 <= limit <= MAX_SOURCE_BATCHES):
        raise staff.SpoolError("invalid learner publication scope")
    source, root = staff._path(source_spool), staff._path(output)
    if source == root or source in root.parents or root in source.parents:
        raise staff.SpoolError("source and learner spools must be separate")

    def inspect_publish():
        rows = _source(source, exercise_id)
        previous, initialized = _existing(root, exercise_id, rows)
        chosen = rows[previous:previous + limit]
        if execute:
            # An initial HEAD precedes batch publication; retry can recover a
            # renamed/fsynced batch after a later HEAD-write failure.
            if not initialized or staff._load(staff._safe_file(root / "HEAD.json", 16384)) != _head(exercise_id, rows[:previous]):
                staff._head(root, _head(exercise_id, rows[:previous]))
            for index, row in enumerate(chosen, previous + 1):
                _publish(root, row)
                staff._head(root, _head(exercise_id, rows[:index]))
        return {"scope": "learner_audit_local_publication", "writes_performed": execute,
                "source_batches_selected": len(chosen),
                "source_batches_remaining": len(rows) - previous - len(chosen),
                "events_selected": sum(row[2]["events"] for row in chosen),
                "published_events": _head(exercise_id, rows[:previous + (len(chosen) if execute else 0)])["events"],
                "splunk_ingestion_verified": False, "external_readiness_verified": False}

    rows = _source(source, exercise_id)  # Validate before creating anything.
    _existing(root, exercise_id, rows)
    if not execute:
        return inspect_publish()
    if not root.exists():
        root.mkdir(mode=0o700)
        staff._sync(root.parent)
    staff._directory(root)
    with staff._lock(root):
        return inspect_publish()


class SafeParser(argparse.ArgumentParser):
    def error(self, _message):
        self.exit(2, "Invalid learner export arguments. Use --help.\n")


def main(argv=None):
    parser = SafeParser(description=__doc__)
    parser.add_argument("--source-spool", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--exercise-id", required=True)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = export(args.source_spool, args.output, exercise_id=args.exercise_id,
                        limit=args.limit, execute=args.execute)
    except (OSError, ValueError, KeyError, TypeError, RecursionError):
        print("Learner publication blocked. Preserve both spools; inspect integrity, permissions and scope.", file=sys.stderr)
        return 1
    print(staff._json(report).decode(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
