"""Incremental private publication, source integrity and crash recovery."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
from pathlib import Path

import pytest

from dashboard import event_spool as spool
from dashboard.auth import PortalPrincipal
from dashboard.service import PortalService
from dashboard.store import PortalStore
from shared.events import EventBuilder, EventContext, EventValidator, entity

EXERCISE = "operation-silent-spider"


def build(run="run-a", exercise=EXERCISE):
    return EventBuilder(
        EventContext(exercise, run, "facilitator", "spool-test", "1.0.0")
    )


def event(builder, *, visibility="participant", **overrides):
    return builder.build(
        event_type="exercise.spool.test",
        phase="identity",
        actor=entity("system", "synthetic-test"),
        action="exercise.spool.test",
        target=entity("scenario_run", builder.context.run_id),
        outcome_status="success",
        visibility=visibility,
        message="Synthetic probe",
        dry_run=True,
        data={"nested": {"observed": True}, **overrides},
    )


@pytest.fixture
def source(tmp_path):
    database = tmp_path / "portal.sqlite3"
    store = PortalStore(database)
    builder = build()
    initial = [event(builder) for _ in range(3)]
    for item in initial:
        store.append_event(item)
    yield database, store, builder, initial
    store.close()


def publish(database, root, **options):
    return spool.export(database, root, exercise_id=EXERCISE, execute=True, **options)


def read_events(root):
    return [
        json.loads(line)
        for path in sorted(root.glob("batch-*/events.jsonl"))
        for line in path.read_text().splitlines()
    ]


def tree(root):
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_preview_reads_without_writes_or_portal_initialization(
    source, tmp_path, monkeypatch
):
    database, store, _builder, initial = source
    root = tmp_path / "not-created"
    before = database.read_bytes()

    def forbidden(*_args, **_kwargs):
        raise AssertionError("preview attempted a write or portal construction")

    monkeypatch.setattr(spool, "_write", forbidden)
    monkeypatch.setattr(spool, "_publish", forbidden)
    monkeypatch.setattr(PortalStore, "_initialize", forbidden)
    result = spool.export(database, root, exercise_id=EXERCISE, limit=2)
    assert not root.exists() and database.read_bytes() == before
    assert store.events(EXERCISE, "run-a") == initial
    assert result == {
        "scope": "staff_only_local_publication",
        "exercise_id": EXERCISE,
        "writes_performed": False,
        "events_selected": 2,
        "bytes_selected": result["bytes_selected"],
        "events_remaining": 1,
        "published_event_count": 0,
        "splunk_ingestion_verified": False,
    }


def test_repeated_bounded_publication_preserves_canonical_events_and_database(
    source, tmp_path
):
    database, _store, _builder, initial = source
    before = database.read_bytes()
    root = tmp_path / "spool"
    assert publish(database, root, limit=2)["events_selected"] == 2
    first_files = tree(root)
    assert publish(database, root, limit=2)["events_selected"] == 1
    assert publish(database, root, limit=2)["events_selected"] == 0
    assert read_events(root) == initial and database.read_bytes() == before
    for name, content in first_files.items():
        if name != "HEAD.json":
            assert tree(root)[name] == content
    assert len(list(root.glob("batch-*"))) == 2
    assert root.stat().st_mode & 0o777 == 0o700
    assert all(
        path.stat().st_mode & 0o777 == 0o600
        for path in root.rglob("*")
        if path.is_file()
    )
    before = tree(root)
    preview = spool.export(database, root, exercise_id=EXERCISE)
    assert not preview["writes_performed"] and preview["published_event_count"] == 3
    assert tree(root) == before


def test_real_reset_retains_old_archive_and_new_run_sequences_privately(tmp_path):
    database = tmp_path / "portal.sqlite3"
    store = PortalStore(database)
    service = PortalService(store, run_id="old-play")
    principal = PortalPrincipal("staff-test", "facilitator")
    root = tmp_path / "spool"
    service.start_run(principal)
    service.run.fail_safe_stop("Stopped developer probe")
    publish(database, root)
    first = read_events(root)
    service.reset_run(new_run_id="fresh-play", principal=principal)
    service.start_run(principal)
    publish(database, root)
    all_events = read_events(root)
    assert all_events[: len(first)] == first
    assert len({item["event_id"] for item in all_events}) == len(all_events)
    assert {item["run_id"] for item in all_events} == {"old-play", "fresh-play"}
    audit = next(
        item
        for item in all_events
        if item["event_type"] == "evaluation.archive.created"
    )
    assert audit["visibility"] == "evaluator" and audit["run_id"] == "old-play"
    participant = service.participant_evidence(
        PortalPrincipal("analyst", "soc_analyst")
    )
    assert audit["event_id"] not in json.dumps(participant)
    assert store.events(EXERCISE, "fresh-play") == [
        item for item in all_events if item["run_id"] == "fresh-play"
    ]
    store.close()


def test_scope_filters_other_exercises_and_interleaved_run_sequences(source, tmp_path):
    database, store, builder, initial = source
    second = build("run-b")
    store.append_event(event(build(exercise="different-exercise")))
    other_run = event(
        second, visibility="evaluator", staff_analysis="Private review not for learners"
    )
    store.append_event(other_run)
    same_run = event(builder)
    store.append_event(same_run)
    root = tmp_path / "spool"
    publish(database, root, limit=4)
    publish(database, root, limit=4)
    assert read_events(root) == [*initial, other_run, same_run]
    assert not spool.export(database, tmp_path / "unused", exercise_id="x' OR 1=1 --")[
        "events_selected"
    ]
    before = tree(root)
    with pytest.raises(spool.SpoolError):
        spool.export(database, root, exercise_id="different-exercise", execute=True)
    assert tree(root) == before


def test_read_only_sql_connection_and_wal_append(source, tmp_path):
    database, store, builder, _initial = source
    store._connection.execute("PRAGMA journal_mode = WAL")
    root = tmp_path / "spool"
    publish(database, root)
    with spool._database(database) as connection:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            connection.execute("DELETE FROM events")
    store.append_event(event(builder))
    assert publish(database, root)["events_selected"] == 1


def test_same_spool_is_exclusively_locked(source, tmp_path):
    database, _store, _builder, initial = source
    root = tmp_path / "spool"
    publish(database, root, limit=1)
    before = tree(root)
    with spool._lock(root):
        with pytest.raises(spool.SpoolError, match="publisher"):
            publish(database, root)
    assert tree(root) == before
    publish(database, root)
    assert read_events(root) == initial


@pytest.mark.parametrize("boundary", ["stage", "head", "directory-sync"])
def test_publication_failures_recover_without_visible_partial_or_duplicate_batch(
    source, tmp_path, monkeypatch, boundary
):
    database, _store, _builder, initial = source
    root = tmp_path / "spool"
    original_write, original_head, original_sync = (
        spool._write,
        spool._head,
        spool._sync,
    )
    failed = False

    def write(path, content):
        if path.name == "manifest.json":
            raise OSError("simulated incomplete stage")
        return original_write(path, content)

    def head(path, state):
        if state["cursor"]:
            raise OSError("simulated checkpoint crash after publication")
        return original_head(path, state)

    def sync(path):
        nonlocal failed
        if path == root and list(root.glob("batch-*")) and not failed:
            failed = True
            raise OSError("simulated post-rename sync failure")
        return original_sync(path)

    monkeypatch.setattr(
        spool, "_write", write if boundary == "stage" else original_write
    )
    monkeypatch.setattr(spool, "_head", head if boundary == "head" else original_head)
    monkeypatch.setattr(
        spool, "_sync", sync if boundary == "directory-sync" else original_sync
    )
    with pytest.raises(OSError):
        publish(database, root)
    assert read_events(root) == ([] if boundary == "stage" else initial)
    monkeypatch.setattr(spool, "_write", original_write)
    monkeypatch.setattr(spool, "_head", original_head)
    monkeypatch.setattr(spool, "_sync", original_sync)
    publish(database, root)
    assert read_events(root) == initial and len(list(root.glob("batch-*"))) == 1
    assert json.loads((root / "HEAD.json").read_text())["event_count"] == 3


def test_interrupted_first_checkpoint_is_recoverable_without_payload(
    source, tmp_path, monkeypatch
):
    database, _store, _builder, initial = source
    root = tmp_path / "spool"
    original = spool._head

    def interrupted(path, state):
        spool._write(path / (".head-" + "a" * 32), spool._json(state))
        raise OSError("failed first HEAD publication")

    monkeypatch.setattr(spool, "_head", interrupted)
    with pytest.raises(OSError):
        publish(database, root)
    assert not read_events(root)
    monkeypatch.setattr(spool, "_head", original)
    publish(database, root)
    assert read_events(root) == initial


@pytest.mark.parametrize(
    "mutation",
    [
        "missing-last",
        "missing-first",
        "missing-head",
        "bad-head",
        "payload",
        "resigned-payload",
        "manifest",
        "extra-file",
    ],
)
def test_corrupt_or_deleted_committed_evidence_blocks_new_publication(
    source, tmp_path, mutation
):
    database, store, builder, _initial = source
    root = tmp_path / "spool"
    publish(database, root, limit=2)
    publish(database, root, limit=2)
    batches = sorted(root.glob("batch-*"))
    if mutation.startswith("missing-"):
        if mutation == "missing-head":
            (root / "HEAD.json").unlink()
        else:
            shutil.rmtree(batches[-1] if mutation == "missing-last" else batches[0])
    elif mutation == "bad-head":
        (root / "HEAD.json").write_text("{}")
    elif mutation in {"payload", "resigned-payload"}:
        path = batches[0] / "events.jsonl"
        content = path.read_bytes().replace(b"Synthetic probe", b"Tampered probe!")
        path.write_bytes(content)
        if mutation == "resigned-payload":
            manifest_path = batches[0] / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["bytes"] = len(content)
            manifest["events_sha256"] = hashlib.sha256(content).hexdigest()
            manifest_path.write_bytes(spool._json(manifest))
    elif mutation == "manifest":
        (batches[0] / "manifest.json").write_text("{}")
    else:
        (batches[0] / "unexpected.txt").write_text("unexpected")
    store.append_event(event(builder))
    before = tree(root)
    with pytest.raises((spool.SpoolError, OSError)):
        publish(database, root)
    assert tree(root) == before


@pytest.mark.parametrize(
    "mutation",
    [
        "delete",
        "payload",
        "indexed-run",
        "indexed-visibility",
        "sequence-gap",
        "database-rollback",
    ],
)
def test_source_changes_and_rollback_fail_closed(source, tmp_path, mutation):
    database, store, builder, initial = source
    root = tmp_path / "spool"
    publish(database, root, limit=2)
    with store._connection:
        if mutation == "delete":
            store._connection.execute(
                "DELETE FROM events WHERE event_id = ?", (initial[0]["event_id"],)
            )
        elif mutation == "payload":
            altered = dict(initial[0], message="Altered source")
            store._connection.execute(
                "UPDATE events SET payload = ? WHERE event_id = ?",
                (json.dumps(altered), initial[0]["event_id"]),
            )
        elif mutation == "indexed-run":
            store._connection.execute("UPDATE events SET run_id = 'different'")
        elif mutation == "indexed-visibility":
            store._connection.execute("UPDATE events SET visibility = 'evaluator'")
        elif mutation == "sequence-gap":
            store._connection.execute(
                "DELETE FROM events WHERE event_id = ?", (initial[2]["event_id"],)
            )
        else:
            store._connection.execute("DELETE FROM events")
    if mutation == "sequence-gap":
        store.append_event(event(builder))
    before = tree(root)
    with pytest.raises(spool.SpoolError):
        publish(database, root)
    assert tree(root) == before


@pytest.mark.parametrize(
    "payload",
    [
        "{}",
        "not-json",
        '{"password":"PRIVATE-SECRET"}',
        '{"schema_version":"1.0.0","schema_version":"9.0.0"}',
        '{"data":NaN}',
    ],
)
def test_bad_source_payload_never_creates_output_or_echoes_private_body(
    source, tmp_path, capsys, payload
):
    database, store, _builder, initial = source
    with store._connection:
        store._connection.execute(
            "UPDATE events SET payload = ? WHERE event_id = ?",
            (payload, initial[0]["event_id"]),
        )
    root = tmp_path / "spool"
    assert (
        spool.main(
            [
                "--database",
                str(database),
                "--output",
                str(root),
                "--exercise-id",
                EXERCISE,
                "--execute",
            ]
        )
        == 1
    )
    captured = capsys.readouterr()
    assert not root.exists() and not captured.out
    assert "PRIVATE-SECRET" not in captured.err and str(database) not in captured.err


def test_unredacted_fields_and_incompatible_schema_are_refused(source, tmp_path):
    database, store, _builder, initial = source
    for replacement in (
        {**initial[0], "data": {"password": "PRIVATE-SECRET"}},
        {**initial[0], "schema_version": "2.0.0"},
    ):
        with store._connection:
            store._connection.execute(
                "UPDATE events SET payload = ? WHERE event_id = ?",
                (json.dumps(replacement), initial[0]["event_id"]),
            )
        with pytest.raises(spool.SpoolError):
            publish(database, tmp_path / "not-created")
        assert not (tmp_path / "not-created").exists()


@pytest.mark.parametrize("limit", [0, 1001, -1, True, "2"])
def test_invalid_batch_limits_do_not_write(source, tmp_path, limit):
    with pytest.raises(spool.SpoolError):
        publish(source[0], tmp_path / "spool", limit=limit)
    assert not (tmp_path / "spool").exists()


def test_event_and_batch_size_caps_fail_or_stop_before_partial_publication(
    source, tmp_path, monkeypatch
):
    database, _store, _builder, initial = source
    root = tmp_path / "spool"
    assert (
        spool.MAX_EVENT_BYTES == 256 * 1024
        and spool.MAX_BATCH_BYTES == 20 * 1024 * 1024
    )
    monkeypatch.setattr(spool, "MAX_EVENT_BYTES", 1)
    with pytest.raises(spool.SpoolError):
        publish(database, root)
    assert not root.exists()
    monkeypatch.setattr(spool, "MAX_EVENT_BYTES", 256 * 1024)
    monkeypatch.setattr(
        spool,
        "MAX_BATCH_BYTES",
        len(spool._json(initial[0])) + len(spool._json(initial[1])) - 1,
    )
    assert publish(database, root)["events_selected"] == 1
    assert publish(database, root)["events_selected"] == 1
    assert publish(database, root)["events_selected"] == 1
    assert read_events(root) == initial


@pytest.mark.parametrize(
    "target",
    [
        "database-link",
        "root-link",
        "batch-link",
        "payload-link",
        "head-link",
        "payload-hardlink",
        "world-readable",
        "group-writable",
        "unrelated",
    ],
)
def test_unsafe_paths_permissions_and_unrelated_files_are_refused(
    source, tmp_path, target
):
    database, _store, _builder, _initial = source
    root = tmp_path / "spool"
    if target == "database-link":
        linked = tmp_path / "linked.sqlite3"
        linked.symlink_to(database)
        database = linked
    elif target == "root-link":
        root.symlink_to(tmp_path / "missing-root")
    elif target == "unrelated":
        root.mkdir(mode=0o700)
        (root / "user-notes.txt").write_text("keep this")
    else:
        publish(database, root)
        batch = next(root.glob("batch-*"))
        if target == "world-readable":
            root.chmod(0o755)
        elif target == "group-writable":
            (batch / "events.jsonl").chmod(0o660)
        elif target == "payload-hardlink":
            os.link(batch / "events.jsonl", tmp_path / "hardlink")
        else:
            path = (
                batch
                if target == "batch-link"
                else (
                    root / "HEAD.json"
                    if target == "head-link"
                    else batch / "events.jsonl"
                )
            )
            moved = tmp_path / "preserved"
            path.rename(moved)
            path.symlink_to(moved)
    with pytest.raises((spool.SpoolError, OSError)):
        publish(database, root)
    if target == "unrelated":
        assert (root / "user-notes.txt").read_text() == "keep this"


def test_missing_database_unknown_schema_and_database_inside_spool_do_not_write(
    tmp_path,
):
    root = tmp_path / "spool"
    missing = tmp_path / "missing.sqlite3"
    with pytest.raises(spool.SpoolError):
        publish(missing, root)
    assert not missing.exists() and not root.exists()
    database = tmp_path / "unknown.sqlite3"
    with sqlite3.connect(database):
        pass
    with pytest.raises(sqlite3.OperationalError):
        publish(database, root)
    assert not root.exists()
    with pytest.raises(spool.SpoolError):
        publish(database, tmp_path)


def test_cli_default_counts_only_without_network_or_new_services(
    source, tmp_path, capsys, monkeypatch
):
    import socket

    def forbidden(*_args, **_kwargs):
        raise AssertionError("export contacted the network")

    monkeypatch.setattr(socket, "socket", forbidden)
    database, _store, _builder, _initial = source
    root = tmp_path / "spool"
    args = [
        "--database",
        str(database),
        "--output",
        str(root),
        "--exercise-id",
        EXERCISE,
    ]
    assert spool.main(args) == 0
    result = json.loads(capsys.readouterr().out)
    assert not result["writes_performed"] and result["events_selected"] == 3
    assert not root.exists()
    assert spool.main([*args, "--execute"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["writes_performed"] and not result["splunk_ingestion_verified"]
    for item in read_events(root):
        EventValidator().validate(item)


def test_empty_exercise_spool_can_later_publish_first_event(tmp_path):
    database = tmp_path / "empty.sqlite3"
    store = PortalStore(database)
    root = tmp_path / "spool"
    assert publish(database, root)["published_event_count"] == 0
    first = event(build())
    store.append_event(first)
    assert publish(database, root)["published_event_count"] == 1
    assert read_events(root) == [first]
    store.close()


@pytest.mark.parametrize(
    "case_id",
    [
        "path-pass-pass-pass-pass",
        "path-miss-miss-miss-miss",
        "missing-cloud-source",
        "impact-write-fault",
        "recovery-write-fault",
    ],
)
def test_full_play_sources_and_fault_evidence_match_original_ledger_across_reset(
    tmp_path, case_id
):
    from scripts.rehearsal import Driver, cases

    directory = tmp_path / "case"
    directory.mkdir()
    driver = Driver(cases()[case_id], directory)
    database = tmp_path / "copied.sqlite3"
    root = tmp_path / "spool"
    try:
        driver.opening()
        if driver.cloud() and driver.impact():
            driver.finish()
        driver.stop()
        with sqlite3.connect(database) as destination:
            driver.store._connection.backup(destination)
        while publish(database, root, limit=50)["events_remaining"]:
            pass
        original = read_events(root)
        assert original == driver.store.events(EXERCISE, driver.run_id)
        assert any(
            item["source"]["component"] == "endpoint-ad-simulator" for item in original
        )
        driver.reset()
        with sqlite3.connect(database) as destination:
            driver.store._connection.backup(destination)
        while publish(database, root, limit=50)["events_remaining"]:
            pass
        with spool._database(database) as connection:
            expected = [
                json.loads(row[0])
                for row in connection.execute(
                    "SELECT payload FROM events ORDER BY rowid"
                )
            ]
        assert read_events(root) == expected
        assert read_events(root)[: len(original)] == original
        assert publish(database, root)["events_selected"] == 0
        assert len({item["event_id"] for item in expected}) == len(expected)
        assert not driver.service.aar_report()["aggregate_score"]
    finally:
        driver.stop()
        driver.store.close()


@pytest.mark.parametrize("mutation", ["head", "previous", "next"])
def test_boolean_checkpoint_counters_are_not_integers(source, tmp_path, mutation):
    database, _store, _builder, _initial = source
    root = tmp_path / "spool"
    publish(database, root, limit=1)
    if mutation == "head":
        path = root / "HEAD.json"
        content = json.loads(path.read_text())
        content["cursor"] = True
    else:
        path = next(root.glob("batch-*")) / "manifest.json"
        content = json.loads(path.read_text())
        content[mutation]["event_count"] = False if mutation == "previous" else True
    path.write_bytes(spool._json(content))
    with pytest.raises(spool.SpoolError):
        publish(database, root)


def test_demo_preview_is_inert(tmp_path, monkeypatch, capsys):
    from dashboard import event_spool_demo as demo

    def forbidden(*_args, **_kwargs):
        raise AssertionError("preview started the demo")

    monkeypatch.setattr(demo, "demonstrate", forbidden)
    root = tmp_path / "unused"
    assert demo.main(["--output", str(root)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert not result["writes_performed"] and not root.exists()


def test_real_demo_partial_play_has_two_private_batches_and_no_duplicate_repeat(
    tmp_path,
):
    from dashboard.event_spool_demo import demonstrate

    root = tmp_path / "demo"
    result = demonstrate(root)
    assert result["writes_performed"] and not result["live_splunk_verified"]
    assert not result["full_exercise_completed"]
    assert result["archive_review_status"] == "provisional"
    assert result["archive_run_state"] == result["current_run_state"] == "stopped"
    assert result["repeat"]["events_selected"] == 0
    assert (
        result["opening"]["events_remaining"]
        == result["after_reset"]["events_remaining"]
        == 0
    )
    assert len(list((root / "staff-spool").glob("batch-*"))) == 2
    evidence = read_events(root / "staff-spool")
    assert len(evidence) == result["after_reset"]["published_event_count"]
    assert {item["run_id"] for item in evidence} == {
        "spool-demo-before-reset",
        "spool-demo-after-reset",
    }


def test_demo_refuses_missing_or_existing_destination(tmp_path):
    from dashboard.event_spool_demo import main

    with pytest.raises(SystemExit):
        main(["--execute"])
    notes = tmp_path / "team-notes.txt"
    notes.write_text("preserve")
    assert main(["--execute", "--output", str(tmp_path)]) == 1
    assert notes.read_text() == "preserve"
