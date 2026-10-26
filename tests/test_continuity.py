import datetime as dt
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
TOOLS = REPO / "tools" / "continuity"


def run(script, root, stdin=""):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root), PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, str(TOOLS / script)], input=stdin, capture_output=True,
                          text=True, encoding="utf-8", env=env, cwd=root)


def git(root, *args):
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


@pytest.fixture
def project(tmp_path):
    shutil.copytree(REPO / "templates" / "docs", tmp_path / "docs")
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "t@example.com")
    git(tmp_path, "config", "user.name", "t")
    return tmp_path


def commit_all(root):
    git(root, "add", "-A")
    git(root, "commit", "-qm", "x")


def set_first_action(root, day):
    state = root / "docs" / "STATE.md"
    text = state.read_text(encoding="utf-8").replace("YYYY-MM-DD: <the single", f"{day}: <the single")
    state.write_text(text, encoding="utf-8")


def test_not_ready_when_first_action_is_undated(project):
    commit_all(project)
    r = run("relocate.py", project)
    assert r.returncode == 1
    assert "F  '## First action' is not dated today" in r.stdout
    assert not (project / "FIRST_PROMPT.md").exists()


def test_not_ready_with_uncommitted_changes(project):
    set_first_action(project, dt.datetime.now(dt.timezone.utc).date().isoformat())
    r = run("relocate.py", project)
    assert r.returncode == 1
    assert "G  uncommitted changes" in r.stdout


def test_not_ready_when_truth_file_missing(project):
    (project / "docs" / "LESSONS.md").unlink()
    set_first_action(project, dt.datetime.now(dt.timezone.utc).date().isoformat())
    commit_all(project)
    r = run("relocate.py", project)
    assert "T  docs/LESSONS.md is missing or empty" in r.stdout


def test_ready_writes_first_prompt_with_first_action(project):
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    set_first_action(project, today)
    commit_all(project)
    r = run("relocate.py", project)
    assert r.returncode == 0, r.stdout
    assert "RESULT: ready for compaction" in r.stdout
    prompt = (project / "FIRST_PROMPT.md").read_text(encoding="utf-8")
    assert f"{today}: <the single next thing" in prompt
    assert "python tools/continuity/ack.py" in prompt


def test_hook_injects_prompt_and_ack_clears_flag(project):
    (project / "FIRST_PROMPT.md").write_text("# Continue\nFirst action: ship it\n", encoding="utf-8")
    r = run("first_prompt.py", project, stdin='{"source": "compact"}')
    assert r.returncode == 0
    out = json.loads(r.stdout)
    assert out["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "First action: ship it" in out["hookSpecificOutput"]["additionalContext"]
    assert (project / ".continuity" / "first_prompt_pending").exists()
    g = run("guard.py", project, stdin=json.dumps({"cwd": str(project)}))
    assert "A FIX FIRST" in g.stdout
    a = run("ack.py", project)
    assert a.stdout.strip() == "first prompt acknowledged"
    assert not (project / ".continuity" / "first_prompt_pending").exists()
    assert "A ok" in run("guard.py", project, stdin=json.dumps({"cwd": str(project)})).stdout


def test_hook_survives_missing_prompt(project):
    r = run("first_prompt.py", project)
    assert r.returncode == 0
    assert "FIRST_PROMPT.md not readable" in json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]


def write_transcript(path, messages):
    lines = []
    for minutes_ago, text in messages:
        ts = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=minutes_ago)).isoformat().replace("+00:00", "Z")
        lines.append(json.dumps({"type": "user", "timestamp": ts, "message": {"role": "user", "content": text}}))
    lines.append(json.dumps({"type": "user", "timestamp": ts,
                             "message": {"content": [{"type": "tool_result", "content": "ignored"}]}}))
    path.write_text("\n".join(lines), encoding="utf-8")


def test_guard_flags_unrecorded_user_message(project, tmp_path_factory):
    t = tmp_path_factory.mktemp("t") / "session.jsonl"
    write_transcript(t, [(30, "Publish the package on GitHub, of course.")])
    g = run("guard.py", project, stdin=json.dumps({"cwd": str(project), "transcript_path": str(t)}))
    assert "D FIX: 1 user message(s) not recorded" in g.stdout
    with open(project / "docs" / "DECISIONS.md", "a", encoding="utf-8") as f:
        f.write("\n- 2026-01-01 00:00Z, user verbatim: «Publish the package on GitHub, of course.»\n")
    g = run("guard.py", project, stdin=json.dumps({"cwd": str(project), "transcript_path": str(t)}))
    assert "D ok" in g.stdout and "FIX" not in g.stdout


def test_guard_fresh_message_is_record_now_not_gap(project, tmp_path_factory):
    t = tmp_path_factory.mktemp("t") / "session.jsonl"
    write_transcript(t, [(0, "A brand new instruction just typed")])
    g = run("guard.py", project, stdin=json.dumps({"cwd": str(project), "transcript_path": str(t)}))
    assert "record the new user message" in g.stdout


def test_guard_without_transcript_says_unknown_not_ok(project):
    g = run("guard.py", project, stdin=json.dumps({"cwd": str(project)}))
    assert "D ? (no transcript path on stdin)" in g.stdout
