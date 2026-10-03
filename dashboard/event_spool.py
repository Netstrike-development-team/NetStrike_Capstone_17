"""Offline staff-only SQLite-to-JSONL publication; never Splunk acknowledgement."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import sqlite3
import stat
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path

from shared.events import EventValidator, redact_sensitive

VERSION = "1.0.0"
MAX_EVENT_BYTES = 256 * 1024
MAX_BATCH_BYTES = 20 * 1024 * 1024
BATCH_PATTERN = re.compile(r"batch-([0-9]{20})-([0-9]{20})")
EMPTY_DIGEST = hashlib.sha256(b"").hexdigest()


class SpoolError(ValueError):
    """Publication refused; preserve the database and previously published files."""


def _json(value) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SpoolError("duplicate JSON field")
        result[key] = value
    return result


def _constant(_value):
    raise SpoolError("non-finite JSON number")


def _load(value):
    return json.loads(value, object_pairs_hook=_pairs, parse_constant=_constant)


def _safe_file(path: Path, maximum: int) -> bytes:
    """Do not follow symlinks or read devices; bound a single local input."""
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_size > maximum
            or info.st_nlink != 1
        ):
            raise SpoolError("unsafe or oversized spool file")
        if info.st_mode & 0o007 or info.st_mode & 0o020:
            raise SpoolError("spool files must be private and not group-writable")
        content = stream.read(maximum + 1)
        if len(content) > maximum:
            raise SpoolError("oversized spool file")
        return content


def _directory(path: Path) -> None:
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o027:
        raise SpoolError("spool directories must be private and not group-writable")


def _path(value: Path | str) -> Path:
    supplied = Path(value).absolute()
    if ".." in supplied.parts or not supplied.name:
        raise SpoolError("invalid local path")
    # Resolve the caller-selected parent (e.g. macOS /tmp); the leaf and every
    # spool-owned descendant remain non-symlink inputs in a staff-owned directory.
    return supplied.parent.resolve(strict=True) / supplied.name


def _state(exercise_id, cursor=0, count=0, digest=EMPTY_DIGEST):
    return {
        "version": VERSION,
        "exercise_id": exercise_id,
        "cursor": cursor,
        "event_count": count,
        "prefix_sha256": digest,
    }


def _check_state(value, exercise_id):
    if not isinstance(value, dict) or set(value) != set(_state(exercise_id)):
        raise SpoolError("invalid publication checkpoint")
    if value["version"] != VERSION or value["exercise_id"] != exercise_id:
        raise SpoolError("incompatible publication scope")
    if any(
        not isinstance(value[key], int)
        or isinstance(value[key], bool)
        or value[key] < 0
        for key in ("cursor", "event_count")
    ):
        raise SpoolError("invalid checkpoint counters")
    if (
        value["event_count"] > value["cursor"]
        or not isinstance(value["prefix_sha256"], str)
        or not re.fullmatch(r"[0-9a-f]{64}", value["prefix_sha256"])
    ):
        raise SpoolError("invalid checkpoint digest")
    if value["event_count"] == 0 and value != _state(exercise_id):
        raise SpoolError("invalid empty checkpoint")


def _batch(path, exercise_id, previous):
    if {entry.name for entry in path.iterdir()} != {"manifest.json", "events.jsonl"}:
        raise SpoolError("unexpected batch contents")
    manifest = _load(_safe_file(path / "manifest.json", 4096))
    content = _safe_file(path / "events.jsonl", MAX_BATCH_BYTES)
    if set(manifest) != {
        "version",
        "exercise_id",
        "previous",
        "next",
        "first_cursor",
        "event_count",
        "bytes",
        "events_sha256",
    }:
        raise SpoolError("invalid batch manifest")
    following = manifest["next"]
    _check_state(following, exercise_id)
    _check_state(manifest["previous"], exercise_id)
    if (
        manifest["version"] != VERSION
        or manifest["exercise_id"] != exercise_id
        or manifest["previous"] != previous
    ):
        raise SpoolError("invalid batch chain")
    if (
        set(following) != set(previous)
        or following["version"] != VERSION
        or following["exercise_id"] != exercise_id
    ):
        raise SpoolError("invalid batch scope")
    first, cursor, count = (
        manifest["first_cursor"],
        following["cursor"],
        manifest["event_count"],
    )
    if any(
        not isinstance(value, int) or isinstance(value, bool)
        for value in (first, cursor, count, following["event_count"], manifest["bytes"])
    ):
        raise SpoolError("invalid batch counters")
    if (
        not previous["cursor"] < first <= cursor
        or not 1 <= count <= 1000
        or following["event_count"] != previous["event_count"] + count
        or path.name != f"batch-{first:020d}-{cursor:020d}"
    ):
        raise SpoolError("invalid batch range")
    if (
        manifest["bytes"] != len(content)
        or not content.endswith(b"\n")
        or len(content.splitlines()) != count
        or hashlib.sha256(content).hexdigest() != manifest["events_sha256"]
    ):
        raise SpoolError("invalid batch integrity")
    if not isinstance(following["prefix_sha256"], str) or not re.fullmatch(
        r"[0-9a-f]{64}", following["prefix_sha256"]
    ):
        raise SpoolError("invalid prefix digest")
    return manifest


def _batch_paths(entries):
    paths = []
    for entry in entries:
        if entry.name in {"HEAD.json", ".lock"}:
            _safe_file(entry, 4096)
        elif BATCH_PATTERN.fullmatch(entry.name):
            _directory(entry)
            paths.append(entry)
        elif re.fullmatch(r"\.pending-[0-9a-f]{32}", entry.name):
            _directory(entry)  # Incomplete private stages are never monitored/adopted.
        elif re.fullmatch(r"\.head-[0-9a-f]{32}", entry.name):
            _safe_file(entry, 4096)  # Interrupted HEAD replacement, never a checkpoint.
        else:
            raise SpoolError("unrecognized spool contents")
    return sorted(paths)


def _batches(root: Path, exercise_id: str):
    """Verify the entire local chain, including an earlier durable HEAD marker."""
    if not root.exists():
        if root.is_symlink():
            raise SpoolError("linked spool root")
        return _state(exercise_id), False, []
    _directory(root)
    entries = list(root.iterdir())
    if not entries:
        return _state(exercise_id), False, []
    if not (root / "HEAD.json").exists() and not (root / "HEAD.json").is_symlink():
        for entry in entries:
            if entry.name == ".lock":
                _safe_file(entry, 0)
            elif re.fullmatch(r"\.head-[0-9a-f]{32}", entry.name):
                _safe_file(entry, 4096)
            else:
                raise SpoolError("missing checkpoint; preserve evidence")
        return _state(exercise_id), False, []
    head = _load(_safe_file(root / "HEAD.json", 4096))
    _check_state(head, exercise_id)
    previous = _state(exercise_id)
    head_seen = head == previous
    manifests = []
    for path in _batch_paths(entries):
        manifest = _batch(path, exercise_id, previous)
        previous = manifest["next"]
        head_seen = head_seen or head == previous
        manifests.append(manifest)
    if not head_seen:
        raise SpoolError("checkpoint missing from published chain; preserve evidence")
    return previous, True, manifests


@contextmanager
def _database(path: Path):
    if path.is_symlink() or not path.is_file():
        raise SpoolError("database must be an existing real file")
    # Do not instantiate PortalStore: its schema migration is a write.
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only = ON")
        connection.execute("BEGIN")
        yield connection
    finally:
        connection.close()


def _event(row, validator, sequences):
    try:
        if len(row["payload"].encode()) > MAX_EVENT_BYTES:
            raise SpoolError("source event exceeds publication limit")
        event = _load(row["payload"])
        validator.validate(event)
        if redact_sensitive(event) != event:
            raise SpoolError("source event contains unredacted fields")
        if any(
            row[field] != event[field]
            for field in ("event_id", "exercise_id", "run_id", "sequence", "visibility")
        ):
            raise SpoolError("source event index mismatch")
        expected = sequences.get(event["run_id"], 0) + 1
        if event["sequence"] != expected:
            raise SpoolError("source run sequence gap")
        line = _json(event)
        if len(line) > MAX_EVENT_BYTES:
            raise SpoolError("encoded event exceeds publication limit")
        sequences[event["run_id"]] = expected
        return event, line
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError) as exc:
        raise SpoolError("source event validation failed; preserve evidence") from exc


# Keep separate streaming source/batch hashes and counters, rather than buffering
# old event bodies or hiding the two correlation checks in an opaque state object.
def _read(connection, state, limit, manifests):  # pylint: disable=too-many-locals
    """Stream/validate the old prefix; retain at most one bounded new batch."""
    validator = EventValidator()
    sequences = {}
    digest = hashlib.sha256()
    count = 0
    cursor = 0
    batch_index = 0
    batch_digest = hashlib.sha256()
    batch_count = 0
    batch_size = 0
    rows = connection.execute(
        "SELECT rowid AS cursor, * FROM events WHERE exercise_id = ? AND rowid <= ? ORDER BY rowid",
        (state["exercise_id"], state["cursor"]),
    )
    for row in rows:
        event, line = _event(row, validator, sequences)
        digest.update(_json({"cursor": row["cursor"], "event": event}))
        count += 1
        cursor = row["cursor"]
        if batch_index >= len(manifests):
            raise SpoolError("source prefix has no published batch")
        batch = manifests[batch_index]
        if not batch["first_cursor"] <= cursor <= batch["next"]["cursor"]:
            raise SpoolError("source batch range changed")
        batch_digest.update(line)
        batch_count += 1
        batch_size += len(line)
        if cursor == batch["next"]["cursor"]:
            if (
                batch_digest.hexdigest() != batch["events_sha256"]
                or batch_count != batch["event_count"]
                or batch_size != batch["bytes"]
                or _state(state["exercise_id"], cursor, count, digest.hexdigest())
                != batch["next"]
            ):
                raise SpoolError("published batch no longer matches source")
            batch_index += 1
            batch_digest = hashlib.sha256()
            batch_count = batch_size = 0
    if batch_index != len(manifests):
        raise SpoolError("published source events are missing")
    if _state(state["exercise_id"], cursor, count, digest.hexdigest()) != state:
        raise SpoolError("exported source prefix changed or rolled back")
    lines = []
    size = 0
    first = None
    rows = connection.execute(
        "SELECT rowid AS cursor, * FROM events WHERE exercise_id = ? AND rowid > ? ORDER BY rowid LIMIT ?",
        (state["exercise_id"], cursor, limit),
    )
    for row in rows:
        event, line = _event(row, validator, sequences)
        if size + len(line) > MAX_BATCH_BYTES:
            break
        digest.update(_json({"cursor": row["cursor"], "event": event}))
        first = first or row["cursor"]
        cursor = row["cursor"]
        count += 1
        size += len(line)
        lines.append(line)
    pending = connection.execute(
        "SELECT COUNT(*) FROM events WHERE exercise_id = ? AND rowid > ?",
        (state["exercise_id"], cursor),
    ).fetchone()[0]
    return (
        b"".join(lines),
        first,
        _state(state["exercise_id"], cursor, count, digest.hexdigest()),
        pending,
    )


def _write(path: Path, content: bytes):
    descriptor = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
    )
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def _sync(path: Path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _head(root: Path, state):
    pending = root / (".head-" + uuid.uuid4().hex)
    _write(pending, _json(state))
    os.replace(pending, root / "HEAD.json")
    _sync(root)


def _publish(root, previous, following, first, content):
    stage = root / (".pending-" + uuid.uuid4().hex)
    stage.mkdir(mode=0o700)
    manifest = {
        "version": VERSION,
        "exercise_id": previous["exercise_id"],
        "previous": previous,
        "next": following,
        "first_cursor": first,
        "event_count": following["event_count"] - previous["event_count"],
        "bytes": len(content),
        "events_sha256": hashlib.sha256(content).hexdigest(),
    }
    _write(stage / "events.jsonl", content)
    _write(stage / "manifest.json", _json(manifest))
    _sync(stage)
    destination = root / f"batch-{first:020d}-{following['cursor']:020d}"
    if destination.exists() or destination.is_symlink():
        raise SpoolError("batch destination already exists")
    os.rename(stage, destination)
    _sync(root)


@contextmanager
def _lock(root):
    descriptor = os.open(
        root / ".lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600
    )
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_mode & 0o027:
            raise SpoolError("unsafe publisher lock")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise SpoolError("another publisher owns the spool") from exc
        yield
    finally:
        os.close(descriptor)


def export(database, output, *, exercise_id, limit=500, execute=False):
    """One bounded local publication or an advisory read-only preview."""
    if (
        not isinstance(exercise_id, str)
        or not 1 <= len(exercise_id) <= 128
        or not isinstance(limit, int)
        or isinstance(limit, bool)
        or not 1 <= limit <= 1000
    ):
        raise SpoolError("invalid export scope or limit")
    source, root = _path(database), _path(output)
    if source == root or root in source.parents:
        raise SpoolError("database cannot be inside the spool")

    def inspect_and_publish():
        previous, initialized, manifests = _batches(root, exercise_id)
        with _database(source) as connection:
            content, first, following, pending = _read(
                connection, previous, limit, manifests
            )
        if execute:
            if not initialized:
                _head(root, previous)
            elif _load(_safe_file(root / "HEAD.json", 4096)) != previous:
                _head(
                    root, previous
                )  # Recover a fully committed batch after a HEAD-write crash.
            if content:
                _publish(root, previous, following, first, content)
                _head(root, following)
        return {
            "scope": "staff_only_local_publication",
            "exercise_id": exercise_id,
            "writes_performed": execute,
            "events_selected": following["event_count"] - previous["event_count"],
            "bytes_selected": len(content),
            "events_remaining": pending,
            "published_event_count": (
                following["event_count"] if execute else previous["event_count"]
            ),
            "splunk_ingestion_verified": False,
        }

    if not execute:
        return inspect_and_publish()
    # Read/validate inputs before creating a directory or lock. Never initialize
    # an unrelated directory or make a missing source database.
    inspect_and_validate = _batches(root, exercise_id)
    with _database(source) as connection:
        _read(connection, inspect_and_validate[0], limit, inspect_and_validate[2])
    if not root.exists():
        root.mkdir(mode=0o700)
        _sync(root.parent)
    _directory(root)
    with _lock(root):
        return inspect_and_publish()


def main(argv=None):
    """Explicit local file output; stdout contains counts, not staff event bodies."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--exercise-id", required=True)
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--execute", action="store_true")
    arguments = parser.parse_args(argv)
    try:
        result = export(
            arguments.database,
            arguments.output,
            exercise_id=arguments.exercise_id,
            limit=arguments.limit,
            execute=arguments.execute,
        )
    except (OSError, sqlite3.Error, ValueError, KeyError, TypeError, RecursionError):
        print(
            "Event publication blocked. Preserve source/spool evidence; inspect permissions, integrity and scope.",
            file=sys.stderr,
        )
        return 1
    print(_json(result).decode(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
