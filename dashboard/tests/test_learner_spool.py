"""Privacy boundary, immutable publication and interruption recovery."""

import hashlib
import json
import shutil

import pytest

from dashboard import event_spool as staff
from dashboard import learner_spool as learner
from dashboard.store import PortalStore
from shared.events import EventBuilder, EventContext, entity

EXERCISE = "operation-silent-spider"


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.fixture
def source(tmp_path):
    database, root = tmp_path / "portal.sqlite3", tmp_path / "staff"
    store = PortalStore(database)
    for run in ("old-run", "new-run"):
        builder = EventBuilder(EventContext(EXERCISE, run, "module", "helpdesk-simulator", "1.0.0"))
        for visibility in ("participant", "facilitator", "participant"):
            item = builder.build(event_type="helpdesk.identity_reset.completed", phase="identity",
                actor=entity("helpdesk_agent", "tyler"), action="helpdesk.identity_reset",
                target=entity("identity", "sarah"), outcome_status="success", visibility=visibility,
                message="PRIVATE answer and facilitator notes", dry_run=True,
                data={"ticket_id": "HD-1042", "callback_verified": False, "solution": "PRIVATE"})
            store.append_event(item)
    for _ in range(6):
        staff.export(database, root, exercise_id=EXERCISE, limit=1, execute=True)
    store.close()
    return root


def publish(source, output, **options):
    return learner.export(source, output, exercise_id=EXERCISE, **options)


def test_preview_and_bounded_retry_preserve_staff_source(source, tmp_path):
    output = tmp_path / "learner"
    original = snapshot(source)
    report = publish(source, output, limit=2)
    assert not output.exists() and not report["writes_performed"]
    assert report["events_selected"] == 1 and report["source_batches_remaining"] == 4
    for expected in (1, 3, 4):
        assert publish(source, output, limit=2, execute=True)["published_events"] == expected
    before = snapshot(output)
    assert publish(source, output, execute=True)["source_batches_selected"] == 0
    assert snapshot(output) == before and snapshot(source) == original
    events = [json.loads(line) for p in sorted(output.glob("batch-*/events.jsonl")) for line in p.read_text().splitlines()]
    assert len(events) == len({item["event_id"] for item in events}) == 4
    assert {item["run_id"] for item in events} == {"old-run", "new-run"}
    assert "PRIVATE" not in json.dumps(events)
    assert len(list(output.glob("batch-*"))) == 6  # Private-only batches advance too.
    assert output.stat().st_mode & 0o777 == 0o700
    assert all(p.stat().st_mode & 0o777 == 0o600 for p in output.rglob("*") if p.is_file())
    assert not report["splunk_ingestion_verified"] and not report["external_readiness_verified"]


@pytest.mark.parametrize("kind", ["events", "receipt", "head", "source", "rollback"])
def test_changed_retained_history_blocks_without_repair(source, tmp_path, kind):
    output = tmp_path / "learner"
    publish(source, output, execute=True)
    if kind == "rollback":
        shutil.rmtree(sorted(source.glob("batch-*"))[-1])
    else:
        target = {"events": next(output.glob("batch-*/events.jsonl")),
                  "receipt": next(output.glob("batch-*/manifest.json")),
                  "head": output / "HEAD.json", "source": next(source.glob("batch-*/events.jsonl"))}[kind]
        target.write_bytes(b"{}\n")
    before = snapshot(output)
    with pytest.raises((ValueError, OSError)):
        publish(source, output, execute=True)
    assert snapshot(output) == before


@pytest.mark.parametrize("where", ["source-root", "source-file", "output-root", "output-file"])
def test_symlink_is_never_followed(source, tmp_path, where):
    output, linked = tmp_path / "learner", tmp_path / "link"
    if where == "source-root":
        linked.symlink_to(source, target_is_directory=True)
        source = linked
    elif where == "source-file":
        target = next(source.glob("batch-*/events.jsonl"))
        held = tmp_path / "held"
        target.rename(held)
        target.symlink_to(held)
    elif where == "output-root":
        linked.mkdir()
        output.symlink_to(linked, target_is_directory=True)
    else:
        publish(source, output, execute=True)
        target = next(output.glob("batch-*/events.jsonl"))
        held = tmp_path / "held"
        target.rename(held)
        target.symlink_to(held)
    with pytest.raises((ValueError, OSError)):
        publish(source, output, execute=True)


@pytest.mark.parametrize("failure_call", [1, 2])
def test_head_interruption_recovers_without_duplicate_events(source, tmp_path, monkeypatch, failure_call):
    output, original, calls = tmp_path / "learner", staff._head, []

    def fail_once(*args):
        calls.append(True)
        if len(calls) == failure_call:
            raise OSError("simulated interruption")
        return original(*args)

    monkeypatch.setattr(staff, "_head", fail_once)
    with pytest.raises(OSError):
        publish(source, output, execute=True)
    monkeypatch.setattr(staff, "_head", original)
    assert publish(source, output, execute=True)["published_events"] == 4
    assert publish(source, output, execute=True)["events_selected"] == 0


def test_failed_staging_is_private_and_retry_ignores_uncommitted_files(source, tmp_path, monkeypatch):
    output, original = tmp_path / "learner", staff._write

    def fail_manifest(path, content):
        if path.name == "manifest.json":
            raise OSError("synthetic interruption")
        return original(path, content)

    monkeypatch.setattr(staff, "_write", fail_manifest)
    with pytest.raises(OSError):
        publish(source, output, execute=True)
    assert not list(output.glob("batch-*"))
    pending = next(output.glob(".pending-*"))
    assert pending.stat().st_mode & 0o777 == 0o700
    monkeypatch.setattr(staff, "_write", original)
    assert publish(source, output, execute=True)["published_events"] == 4


@pytest.mark.parametrize("limit", [0, 101, True, "2"])
def test_invalid_bound_never_creates_output(source, tmp_path, limit):
    output = tmp_path / "learner"
    with pytest.raises(ValueError):
        publish(source, output, limit=limit, execute=True)
    assert not output.exists()


def test_source_limits_and_wrong_exercise_fail_before_writes(source, tmp_path, monkeypatch):
    output = tmp_path / "learner"
    with pytest.raises(ValueError):
        learner.export(source, output, exercise_id="other", execute=True)
    monkeypatch.setattr(learner, "MAX_SOURCE_BYTES", 1)
    with pytest.raises(ValueError):
        publish(source, output, execute=True)
    assert not output.exists()


def test_cannot_publish_inside_source_or_reuse_canonical_spool(source):
    for output in (source, source / "learner"):
        with pytest.raises(ValueError):
            publish(source, output, execute=True)


def test_cli_failures_do_not_echo_input_or_private_paths(tmp_path, capsys):
    assert learner.main(["--source-spool", str(tmp_path / "PRIVATE-secret"), "--output", str(tmp_path / "new"), "--exercise-id", EXERCISE]) == 1
    captured = capsys.readouterr()
    assert not captured.out and "PRIVATE-secret" not in captured.err
    assert "blocked" in captured.err


@pytest.mark.parametrize("mutation", ["schema", "fact", "duplicate", "sequence", "exercise", "secret"])
def test_consumer_checks_events_even_when_batch_checksums_match(source, tmp_path, mutation):
    event = json.loads(next(source.glob("batch-*/events.jsonl")).read_text())
    second = json.loads(json.dumps(event))
    second["event_id"] = "a461d3db-44d5-432e-a482-9889886c14ce"
    second["sequence"] = 2
    if mutation == "schema":
        second.pop("timestamp")
    elif mutation == "fact":
        second["data"]["ticket_id"] = {"private": "prose"}
    elif mutation == "duplicate":
        second["event_id"] = event["event_id"]
    elif mutation == "sequence":
        second["sequence"] = 3
    elif mutation == "exercise":
        second["exercise_id"] = "different-exercise"
    else:
        second["data"]["password"] = "PRIVATE"
    root, output = tmp_path / "crafted-staff", tmp_path / "learner"
    root.mkdir(mode=0o700)
    content = staff._json(event) + staff._json(second)
    previous = staff._state(EXERCISE)
    following = staff._state(EXERCISE, 2, 2, hashlib.sha256(content).hexdigest())
    staff._publish(root, previous, following, 1, content)
    staff._head(root, following)
    with pytest.raises(ValueError):
        publish(root, output, execute=True)
    assert not output.exists()


def test_rehashed_private_source_change_still_blocks_same_projection(source, tmp_path):
    output = tmp_path / "learner"
    publish(source, output, execute=True)
    batch = sorted(source.glob("batch-*"))[1]
    event = json.loads((batch / "events.jsonl").read_text())
    event["message"] = "Different private staff message"
    content = staff._json(event)
    receipt = json.loads((batch / "manifest.json").read_text())
    receipt.update(bytes=len(content), events_sha256=hashlib.sha256(content).hexdigest())
    (batch / "events.jsonl").write_bytes(content)
    (batch / "manifest.json").write_bytes(staff._json(receipt))
    before = snapshot(output)
    with pytest.raises(ValueError):
        publish(source, output, execute=True)
    assert snapshot(output) == before


def test_concurrent_writer_is_refused_without_mutation(source, tmp_path):
    output = tmp_path / "learner"
    publish(source, output, execute=True)
    before = snapshot(output)
    with staff._lock(output):
        with pytest.raises(ValueError):
            publish(source, output, execute=True)
    assert snapshot(output) == before
