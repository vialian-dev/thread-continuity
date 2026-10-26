"""Subprocess tests: each script runs the way Claude Code runs it (stdin JSON, CLAUDE_PROJECT_DIR)."""
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
TOOLS = REPO / "tools" / "continuity"
UTC = dt.timezone.utc


def run(script, root, stdin="", args=(), env_extra=None):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root), PYTHONIOENCODING="utf-8", **(env_extra or {}))
    return subprocess.run([sys.executable, str(TOOLS / script), *args], input=stdin, capture_output=True,
                          text=True, encoding="utf-8", env=env, cwd=root)


def git(root, *args):
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def today():
    return dt.datetime.now(UTC).date().isoformat()


def commit_all(root):
    git(root, "add", "-A")
    git(root, "commit", "-qm", "x")


@pytest.fixture
def project(tmp_path):
    """Templates copied, nothing filled in, committed, no upstream."""
    root = tmp_path / "proj"
    shutil.copytree(REPO / "templates" / "docs", root / "docs")
    (root / ".gitignore").write_text(".continuity/\n", encoding="utf-8")
    git(root, "init", "-q")
    git(root, "config", "user.email", "t@example.com")
    git(root, "config", "user.name", "t")
    commit_all(root)
    return root


def fill_state(root, first=None, goal="Ship 0.2: 9 review defects -> 0"):
    first = first or f"{today()}: run the test suite and fix the first failure"
    (root / "docs" / "STATE.md").write_text(
        f"# State\n\n## Current goal\n{goal}\n\n## First action\n{first}\n", encoding="utf-8")


@pytest.fixture
def ready(project, tmp_path):
    """Filled state, pushed to a bare upstream."""
    fill_state(project)
    commit_all(project)
    bare = tmp_path / "bare.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    git(project, "remote", "add", "origin", str(bare))
    git(project, "push", "-q", "-u", "origin", "HEAD")
    return project


def transcript(path, messages, extra_lines=()):
    """messages: (minutes_ago, text). Returns path."""
    now = dt.datetime.now(UTC)
    lines = [json.dumps({"type": "user", "timestamp": (now - dt.timedelta(minutes=m)).isoformat().replace("+00:00", "Z"),
                         "message": {"role": "user", "content": text}}) for m, text in messages]
    lines.append(json.dumps({"type": "user", "timestamp": now.isoformat(),
                             "message": {"content": [{"type": "tool_result", "content": "ignored"}]}}))
    lines.extend(extra_lines)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def guard(root, **hook):
    """Run the guard. Unless transcript_path is given (None = omit it), an empty transcript without compaction is used."""
    hook.setdefault("cwd", str(root))
    if "transcript_path" not in hook:
        empty = root.parent / "empty-transcript.jsonl"
        empty.write_text("", encoding="utf-8")
        hook["transcript_path"] = str(empty)
    elif hook["transcript_path"] is None:
        del hook["transcript_path"]
    return run("guard.py", root, stdin=json.dumps(hook)).stdout


def record(root, line):
    with open(root / "docs" / "DECISIONS.md", "a", encoding="utf-8") as f:
        f.write("\n" + line + "\n")


# ---------- relocate.py: READY means the listed checks passed ----------

def test_ready_needs_filled_templates_not_just_a_date(project):
    """Review defect 3: templates untouched except the date gave READY."""
    state = project / "docs" / "STATE.md"
    state.write_text(state.read_text(encoding="utf-8").replace("YYYY-MM-DD:", f"{today()}:"), encoding="utf-8")
    commit_all(project)
    r = run("relocate.py", project, args=["--no-remote"])
    assert r.returncode == 1
    assert "'Current goal' still contains a template placeholder" in r.stdout
    assert "'First action' still contains a template placeholder" in r.stdout


def test_no_upstream_is_not_ready_unless_declared(project):
    fill_state(project)
    commit_all(project)
    r = run("relocate.py", project)
    assert r.returncode == 1 and "branch has no upstream" in r.stdout
    r = run("relocate.py", project, args=["--no-remote"])
    assert r.returncode == 0 and "P skipped: --no-remote" in r.stdout


def test_unpushed_commit_is_not_ready(ready):
    record(ready, "- note")
    commit_all(ready)
    r = run("relocate.py", ready)
    assert r.returncode == 1 and "1 commit(s) not pushed" in r.stdout


def test_ready_leaves_tree_clean_and_names_unchecked_d(ready):
    """Review defect 3: after READY the tree held an uncommitted FIRST_PROMPT.md."""
    r = run("relocate.py", ready)
    assert r.returncode == 0, r.stdout
    assert "RESULT: ready for compaction" in r.stdout
    assert "D not checked here" in r.stdout
    out = subprocess.run(["git", "status", "--porcelain"], cwd=ready, capture_output=True, text=True).stdout
    assert out == ""
    assert (ready / ".continuity" / "snapshot.json").is_file()


def test_undated_first_action_and_missing_file(project):
    fill_state(project, first="run the tests")
    (project / "docs" / "LESSONS.md").unlink()
    commit_all(project)
    r = run("relocate.py", project, args=["--no-remote"])
    assert "not dated today" in r.stdout and "docs/LESSONS.md missing" in r.stdout


def test_relocate_checks_decisions_with_transcript(ready, tmp_path):
    t = transcript(tmp_path / "s.jsonl", [(30, "Deploy only after the review passes")])
    r = run("relocate.py", ready, args=["--transcript", str(t)])
    assert r.returncode == 1 and "1 user message(s) not recorded" in r.stdout


# ---------- snapshot + first prompt: no stale plan presented as current ----------

def test_precompact_snapshot_then_fresh_first_prompt(ready, tmp_path):
    t = transcript(tmp_path / "s.jsonl", [])
    s = run("snapshot.py", ready, stdin=json.dumps({"cwd": str(ready), "trigger": "auto", "session_id": "S1",
                                                     "transcript_path": str(t)}))
    assert s.returncode == 0
    snap = json.loads((ready / ".continuity" / "snapshot.json").read_text(encoding="utf-8"))
    r = run("first_prompt.py", ready, stdin=json.dumps({"cwd": str(ready), "session_id": "S1", "source": "compact"}))
    ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "WARNINGS" not in ctx
    assert "run the test suite and fix the first failure" in ctx
    assert f"Snapshot {snap['id']}" in ctx
    assert re.search(r"ack\.py [0-9a-f]{8}\n", ctx)


def test_stale_snapshot_is_rebuilt_not_presented(ready):
    """Review defect 4: an old FIRST_PROMPT.md was inserted without a freshness check."""
    run("relocate.py", ready)
    fill_state(ready, first=f"{today()}: NEW PLAN publish to GitHub")
    commit_all(ready)
    r = run("first_prompt.py", ready, stdin=json.dumps({"cwd": str(ready), "session_id": "S1"}))
    out = json.loads(r.stdout)
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert "is stale" in ctx and "rebuilt from the current files" in ctx
    assert "NEW PLAN publish to GitHub" in ctx and "run the test suite" not in ctx
    assert "Warnings" in out["systemMessage"]


def test_missing_snapshot_is_reported(ready):
    r = run("first_prompt.py", ready, stdin=json.dumps({"cwd": str(ready), "session_id": "S1"}))
    assert "no snapshot (missing)" in json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]


def test_manual_compact_blocked_only_when_asked(project):
    r = run("snapshot.py", project, stdin=json.dumps({"cwd": str(project), "trigger": "manual"}))
    assert r.returncode == 0
    r = run("snapshot.py", project, stdin=json.dumps({"cwd": str(project), "trigger": "manual"}),
            env_extra={"CONTINUITY_BLOCK_MANUAL": "1"})
    assert r.returncode == 2 and "compaction blocked" in r.stderr
    r = run("snapshot.py", project, stdin=json.dumps({"cwd": str(project), "trigger": "auto"}),
            env_extra={"CONTINUITY_BLOCK_MANUAL": "1"})
    assert r.returncode == 0  # automatic compaction is never blocked


# ---------- acknowledgement: per session, bound to the snapshot ----------

def precompact(root, session):
    run("snapshot.py", root, stdin=json.dumps({"cwd": str(root), "trigger": "auto", "session_id": session}))


def restore(root, session):
    """SessionStart(compact) for one session; returns the acknowledgement token printed in its prompt."""
    out = run("first_prompt.py", root, stdin=json.dumps({"cwd": str(root), "session_id": session})).stdout
    ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    return re.search(r"ack\.py ([0-9a-f]{8})\n", ctx).group(1)


def test_ack_requires_the_token(ready):
    precompact(ready, "S1")
    token = restore(ready, "S1")
    assert "A FIX FIRST" in guard(ready, session_id="S1")
    assert run("ack.py", ready).returncode == 2
    bad = run("ack.py", ready, args=["deadbeef"])
    assert bad.returncode == 1 and "does not match" in bad.stdout
    snap_id = json.loads((ready / ".continuity" / "snapshot.json").read_text(encoding="utf-8"))["id"]
    assert run("ack.py", ready, args=[snap_id]).returncode == 1  # the snapshot id is not the token
    assert "A FIX FIRST" in guard(ready, session_id="S1")
    assert run("ack.py", ready, args=[token]).returncode == 0
    assert "A ok" in guard(ready, session_id="S1")


def test_sessions_do_not_acknowledge_for_each_other(ready):
    """Review defect 5: session A's ack cleared session B's flag (sequential compactions)."""
    precompact(ready, "A")
    token_a = restore(ready, "A")
    record(ready, "- change between compactions")
    commit_all(ready)
    git(ready, "push", "-q")
    precompact(ready, "B")
    restore(ready, "B")
    run("ack.py", ready, args=[token_a])
    assert "A ok" in guard(ready, session_id="A")
    assert "A FIX FIRST" in guard(ready, session_id="B")


def test_overlapping_compactions_from_one_snapshot_stay_separate(ready):
    """Review 2, R2-2: PreCompact(A), PreCompact(B), SessionStart(A), SessionStart(B), ack(A) cleared B too."""
    precompact(ready, "A")
    precompact(ready, "B")
    token_a = restore(ready, "A")
    token_b = restore(ready, "B")
    assert token_a != token_b
    assert run("ack.py", ready, args=[token_a]).returncode == 0
    assert "A ok" in guard(ready, session_id="A")
    assert "A FIX FIRST" in guard(ready, session_id="B")
    assert run("ack.py", ready, args=[token_b]).returncode == 0
    assert "A ok" in guard(ready, session_id="B")


def test_unwritable_state_is_not_reported_as_ok(ready, tmp_path):
    """Review defect 6: .continuity as a plain file -> hook 'succeeded', guard said A ok."""
    (ready / ".continuity").write_text("not a directory", encoding="utf-8")
    r = run("first_prompt.py", ready, stdin=json.dumps({"cwd": str(ready), "session_id": "S1"}))
    out = json.loads(r.stdout)
    assert "not writable" in out["systemMessage"]
    t = transcript(tmp_path / "s.jsonl", [], extra_lines=[json.dumps(
        {"type": "system", "subtype": "compact_boundary", "timestamp": dt.datetime.now(UTC).isoformat()})])
    assert "A ? (compaction at" in guard(ready, session_id="S1", transcript_path=str(t))


def test_no_session_id_is_unknown(ready):
    assert "A ? (no session id" in guard(ready)


# ---------- decisions: full text, tri-state ----------

def test_truncated_record_is_not_ok(ready, tmp_path):
    """Review defect 1: the first 60 characters kept, 'DO NOT deploy to production' dropped -> D ok."""
    msg = "Prepare the release notes, update the changelog and tag the version today. DO NOT deploy to production."
    t = transcript(tmp_path / "s.jsonl", [(30, msg)])
    record(ready, "- 2026-01-01 10:00Z, user verbatim: «Prepare the release notes, update the changelog and tag the version today.»")
    assert "D FIX: 1 user message(s)" in guard(ready, session_id="S", transcript_path=str(t))
    record(ready, f"- 2026-01-01 10:00Z, user verbatim: «{msg}»")
    assert "D ok (1 checked)" in guard(ready, session_id="S", transcript_path=str(t))


def test_short_message_needs_its_own_time(ready, tmp_path):
    t = transcript(tmp_path / "s.jsonl", [(30, "yes")])
    record(ready, "- 2000-01-01 00:00Z, user verbatim: «yes» Consequence: unrelated old yes")
    assert "D FIX" in guard(ready, session_id="S", transcript_path=str(t))
    hhmm = (dt.datetime.now(UTC) - dt.timedelta(minutes=30)).strftime("%H:%M")
    record(ready, f"- {today()} {hhmm}Z, user verbatim: «yes»")
    assert "D ok" in guard(ready, session_id="S", transcript_path=str(t))


def test_angle_bracket_user_text_is_checked(ready, tmp_path):
    """Review defect 2: '<request>Do not deploy</request>' was skipped -> D ok."""
    t = transcript(tmp_path / "s.jsonl", [(30, "<request>Do not deploy</request>"),
                                          (30, "<system-reminder>internal</system-reminder>")])
    assert "D FIX: 1 user message(s)" in guard(ready, session_id="S", transcript_path=str(t))


def test_unreadable_transcript_lines_are_unknown(ready, tmp_path):
    """Review defect 2: a transcript of invalid JSON gave D ok."""
    t = tmp_path / "bad.jsonl"
    t.write_text("{not json\n{also not json\n", encoding="utf-8")
    assert "D ? (2 transcript line(s) unreadable)" in guard(ready, session_id="S", transcript_path=str(t))


def test_completed_broken_last_line_counts_unterminated_tail_does_not(ready, tmp_path):
    """Review 2, R2-4: a newline-terminated broken last line was ignored -> D ok."""
    msg = "A properly recorded instruction for the team"
    record(ready, f"- 10:00Z, user verbatim: «{msg}»")
    t = transcript(tmp_path / "s.jsonl", [(30, msg)], extra_lines=['{"type":"user", broken}'])
    assert "D ? (1 transcript line(s) unreadable)" in guard(ready, session_id="S", transcript_path=str(t))
    t.write_text(t.read_text(encoding="utf-8").rstrip("\n"), encoding="utf-8")  # now an unterminated tail
    assert "D ok (1 checked)" in guard(ready, session_id="S", transcript_path=str(t))


def test_repeated_short_answer_is_checked_each_time(ready, tmp_path):
    """Review 2, R2-3: two 'yes' at different times collapsed into one; the second was never checked."""
    t = transcript(tmp_path / "s.jsonl", [(90, "yes"), (30, "yes")])
    first = (dt.datetime.now(UTC) - dt.timedelta(minutes=90)).strftime("%H:%M")
    record(ready, f"- {today()} {first}Z, user verbatim: «yes»")
    assert "D FIX: 1 user message(s)" in guard(ready, session_id="S", transcript_path=str(t))
    second = (dt.datetime.now(UTC) - dt.timedelta(minutes=30)).strftime("%H:%M")
    record(ready, f"- {today()} {second}Z, user verbatim: «yes»")
    assert "D ok (2 checked)" in guard(ready, session_id="S", transcript_path=str(t))


def test_fresh_unrecorded_message_blocks_readiness_before_compaction(ready, tmp_path):
    """Review 2, R2-1: a 60-second-old unrecorded message gave READY and a snapshot with no problems."""
    t = transcript(tmp_path / "s.jsonl", [(1, "DO NOT deploy to production until the owner approves.")])
    assert "record the new user message now" in guard(ready, session_id="S", transcript_path=str(t))
    r = run("relocate.py", ready, args=["--transcript", str(t)])
    assert r.returncode == 1 and "1 user message(s) not recorded" in r.stdout
    run("snapshot.py", ready, stdin=json.dumps({"cwd": str(ready), "trigger": "auto", "session_id": "S",
                                                 "transcript_path": str(t)}))
    snap = json.loads((ready / ".continuity" / "snapshot.json").read_text(encoding="utf-8"))
    assert any("not recorded verbatim" in p for p in snap["problems"])
    ctx = json.loads(run("first_prompt.py", ready, stdin=json.dumps({"cwd": str(ready), "session_id": "S"})).stdout)
    assert "not recorded verbatim" in ctx["hookSpecificOutput"]["additionalContext"]


def test_no_record_and_no_transcript_is_unknown(ready, tmp_path):
    """Review 2, R2-5: session id present, no record, no transcript -> A ok."""
    assert "A ? (transcript unavailable" in guard(ready, session_id="S9", transcript_path=None)
    t = transcript(tmp_path / "s.jsonl", [])
    assert "A ok" in guard(ready, session_id="S9", transcript_path=str(t))  # transcript shows no compaction
    (ready / ".continuity" / "sessions").mkdir(parents=True)
    (ready / ".continuity" / "sessions" / "S9.json").write_text("[]", encoding="utf-8")
    assert "A ? (session record malformed)" in guard(ready, session_id="S9", transcript_path=str(t))


def test_empty_window_says_nothing_to_check(ready, tmp_path):
    t = transcript(tmp_path / "s.jsonl", [(60 * 40, "older than the window")])
    assert "D nothing to check" in guard(ready, session_id="S", transcript_path=str(t))


def test_fresh_message_is_record_now(ready, tmp_path):
    t = transcript(tmp_path / "s.jsonl", [(0, "A brand new instruction just typed")])
    out = guard(ready, session_id="S", transcript_path=str(t))
    assert "D ok (1 checked); record the new user message now" in out


def test_secret_in_message_is_matched_as_redacted_and_flagged_if_written(ready, tmp_path):
    msg = "Use the key sk-abcdefghijklmnopqrstuvwx for the staging bot"
    t = transcript(tmp_path / "s.jsonl", [(30, msg)])
    record(ready, "- 10:00Z, user verbatim: «Use the key [REDACTED] for the staging bot»")
    out = guard(ready, session_id="S", transcript_path=str(t))
    assert "D ok" in out and "S WARN" not in out
    record(ready, f"- 10:00Z, user verbatim: «{msg}»")
    assert "S WARN: 1 secret-like value(s)" in guard(ready, session_id="S", transcript_path=str(t))


# ---------- malformed input never crashes a hook (review defect 7) ----------

@pytest.mark.parametrize("script", ["guard.py", "first_prompt.py", "snapshot.py"])
@pytest.mark.parametrize("stdin", ["[]", "not json", "", '{"cwd": 5, "session_id": ["x"]}'])
def test_hooks_survive_malformed_input(ready, script, stdin):
    r = run(script, ready, stdin=stdin)
    assert r.returncode == 0, r.stderr


def test_naive_timestamp_and_bad_utf8_prompt(ready, tmp_path):
    t = tmp_path / "s.jsonl"
    t.write_text(json.dumps({"type": "user", "timestamp": dt.datetime.now(UTC).replace(tzinfo=None).isoformat(),
                             "message": {"content": "naive time message here, long enough"}}) + "\n", encoding="utf-8")
    assert "D ok (1 checked)" in guard(ready, session_id="S", transcript_path=str(t))
    run("relocate.py", ready)
    (ready / ".continuity" / "first_prompt.md").write_bytes(b"\xff\xfe broken")
    r = run("first_prompt.py", ready, stdin=json.dumps({"cwd": str(ready), "session_id": "S"}))
    assert r.returncode == 0
    assert "UnicodeDecodeError" in json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]


def test_large_transcript_is_entered_by_seek_and_still_checked(ready, tmp_path):
    """Performance: files above CONTINUITY_SEEK_MIN are entered by binary search on timestamps."""
    now = dt.datetime.now(UTC)
    old = [json.dumps({"type": "assistant", "timestamp": (now - dt.timedelta(hours=100, minutes=-i)).isoformat(),
                       "message": {"content": "x" * 900}}) for i in range(3000)]
    t = tmp_path / "big.jsonl"
    recent = json.dumps({"type": "user", "timestamp": (now - dt.timedelta(minutes=30)).isoformat(),
                         "message": {"content": "Recent instruction that must be recorded"}})
    t.write_text("\n".join(old + [recent]) + "\n", encoding="utf-8")
    env = {"CONTINUITY_SEEK_MIN": "0"}
    r = run("guard.py", ready, stdin=json.dumps({"cwd": str(ready), "session_id": "S", "transcript_path": str(t)}),
            env_extra=env)
    assert "D FIX: 1 user message(s)" in r.stdout


def test_tools_inside_the_project_do_not_dirty_git(ready):
    """Found in the live test: __pycache__ written next to the tools made the next check NOT READY."""
    shutil.copytree(TOOLS, ready / "tools" / "continuity", ignore=shutil.ignore_patterns("__pycache__"))
    commit_all(ready)
    git(ready, "push", "-q")
    for _ in range(2):
        r = subprocess.run([sys.executable, "tools/continuity/relocate.py"], cwd=ready, capture_output=True, text=True,
                           env=dict(os.environ, CLAUDE_PROJECT_DIR=str(ready)))
        assert r.returncode == 0, r.stdout
    assert not (ready / "tools" / "continuity" / "__pycache__").exists()


def test_first_message_of_new_session_is_not_unknown(ready, tmp_path):
    """Found in the live test: the transcript file does not exist yet on a new session's first message."""
    missing = tmp_path / "not-yet-written.jsonl"
    run("session_start.py", ready, stdin=json.dumps({"cwd": str(ready), "session_id": "NEW", "source": "startup"}))
    out = guard(ready, session_id="NEW", transcript_path=str(missing))
    assert "A wait (session registered at start; transcript expected)" in out
    assert "D wait (session registered at start; transcript expected)" in out
    r = run("relocate.py", ready, args=["--transcript", str(missing)])
    assert r.returncode == 1 and "could not check decisions: transcript file not available" in r.stdout


def test_missing_transcript_does_not_reclassify_existing_session_as_new(ready, tmp_path):
    """Review 3: deleting the transcript of a compacted session turned A ? / D FIX into A ok / D nothing."""
    boundary = json.dumps({"type": "system", "subtype": "compact_boundary",
                           "timestamp": (dt.datetime.now(UTC) - dt.timedelta(minutes=20)).isoformat()})
    t = transcript(tmp_path / "s.jsonl", [(30, "An instruction that was never recorded anywhere")],
                   extra_lines=[boundary])
    before = guard(ready, session_id="OLD", transcript_path=str(t))
    assert "A ? (compaction at" in before and "D FIX: 1" in before
    t.unlink()
    after = guard(ready, session_id="OLD", transcript_path=str(t))
    assert "A ? (transcript unavailable" in after
    assert "D ? (transcript file not available)" in after


def test_session_start_does_not_overwrite_a_pending_record(ready):
    precompact(ready, "S1")
    restore(ready, "S1")
    run("session_start.py", ready, stdin=json.dumps({"cwd": str(ready), "session_id": "S1", "source": "clear"}))
    assert "A FIX FIRST" in guard(ready, session_id="S1")


def registered(root, session, minutes_ago):
    d = root / ".continuity" / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    started = (dt.datetime.now(UTC) - dt.timedelta(minutes=minutes_ago)).isoformat()
    (d / f"{session}.json").write_text(json.dumps({"pending": False, "started": started, "source": "startup"}),
                                       encoding="utf-8")


@pytest.mark.parametrize("minutes_ago, a_line, d_line", [
    (5, "A wait (session registered at start", "D wait (session registered at start"),
    (11, "A ? (transcript unavailable", "D ? (transcript file not available)"),
])
def test_registered_session_with_vanished_transcript_is_never_ok(ready, tmp_path, minutes_ago, a_line, d_line):
    """Review 4: registered 5 min ago, transcript with a compaction and an unrecorded message, then deleted ->
    A ok / D nothing (and A ok / D ? after 11 min)."""
    registered(ready, "R", minutes_ago)
    boundary = json.dumps({"type": "system", "subtype": "compact_boundary",
                           "timestamp": (dt.datetime.now(UTC) - dt.timedelta(minutes=2)).isoformat()})
    t = transcript(tmp_path / "s.jsonl", [(3, "Unrecorded instruction given in this session")], extra_lines=[boundary])
    before = guard(ready, session_id="R", transcript_path=str(t))
    assert "A ? (compaction at" in before and "D FIX: 1" in before
    t.unlink()
    after = guard(ready, session_id="R", transcript_path=str(t))
    assert a_line in after and d_line in after
    assert "A ok" not in after and "D nothing" not in after


def test_acknowledged_session_with_vanished_transcript_is_unknown(ready):
    precompact(ready, "S1")
    run("ack.py", ready, args=[restore(ready, "S1")])
    assert "A ok" in guard(ready, session_id="S1")
    assert "A ? (transcript unavailable" in guard(ready, session_id="S1", transcript_path=None)


def test_config_maps_an_existing_truth_set(ready, tmp_path):
    """continuity.json: a project keeps its own file names, heading text and date format (B-455)."""
    day = dt.datetime.now(UTC).strftime("%d.%m")
    (ready / "docs" / "MVP.md").write_text(
        "# MVP\n\n### ТЕКУЩАЯ ЦЕЛЬ\nCOO prototype: 0 of 6 steps -> 6\n\n"
        f"### ПЕРВОЕ ДЕЙСТВИЕ ТРЕДА consilium (night move)\n00 {day} 12:00 ET unfreeze everything\n"
        "01 then the prototype\n\n## Other\nx\n", encoding="utf-8")
    (ready / "docs" / "RESHENIYA.md").write_text("# Decisions\n", encoding="utf-8")
    (ready / "continuity.json").write_text(json.dumps({
        "truth_files": ["docs/MVP.md", "docs/RESHENIYA.md"], "state_file": "docs/MVP.md",
        "decisions_file": "docs/RESHENIYA.md", "goal_section": "ТЕКУЩАЯ ЦЕЛЬ",
        "first_action_section": "ПЕРВОЕ ДЕЙСТВИЕ ТРЕДА", "date_formats": ["%d.%m"],
        "read_first": ["compaction_onboarding.md", "docs/MVP.md"]}, ensure_ascii=False), encoding="utf-8")
    commit_all(ready)
    git(ready, "push", "-q")
    r = run("relocate.py", ready)
    assert r.returncode == 0, r.stdout
    prompt = (ready / ".continuity" / "first_prompt.md").read_text(encoding="utf-8")
    assert f"00 {day} 12:00 ET unfreeze everything" in prompt and "01 then the prototype" in prompt
    assert "\nx\n" not in prompt  # the section ends at the next heading of the same or higher level
    assert "Read: compaction_onboarding.md, docs/MVP.md." in prompt
    t = transcript(tmp_path / "s.jsonl", [(30, "An instruction recorded in the project's own decisions file")])
    assert "D FIX: 1 user message(s) not recorded verbatim in docs/RESHENIYA.md" in guard(
        ready, session_id="S", transcript_path=str(t))


@pytest.mark.parametrize("content, reason", [
    ("{not json", "is not valid JSON"),
    ('{"state_flie": "docs/MVP.md"}', "unknown keys ['state_flie']"),
    ('{"truth_files": "docs/MVP.md"}', "truth_files must be a list of strings"),
])
def test_bad_config_is_not_ready(ready, content, reason):
    (ready / "continuity.json").write_text(content, encoding="utf-8")
    commit_all(ready)
    git(ready, "push", "-q")
    r = run("relocate.py", ready)
    assert r.returncode == 1 and reason in r.stdout


def test_comparison_signs_are_not_placeholders(ready):
    """Found installing 0.3 in a real project: 'quota < 99 %, ... ->' was taken for a <placeholder>."""
    fill_state(ready, goal="Keep quota < 99 %, then move threads -> COO")
    commit_all(ready)
    git(ready, "push", "-q")
    assert run("relocate.py", ready).returncode == 0
