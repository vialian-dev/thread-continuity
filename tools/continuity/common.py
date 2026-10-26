"""Shared paths, git access, hook input and snapshot logic for the thread-continuity tools."""
import datetime as dt
import hashlib
import json
import os
import secrets
import re
import subprocess
import sys
from pathlib import Path

TRUTH_FILES = (
    "docs/STATE.md",
    "docs/DECISIONS.md",
    "docs/PROGRESS.md",
    "docs/BACKLOG.md",
    "docs/LESSONS.md",
)
STATE_DIR = ".continuity"
SNAPSHOT = "snapshot.json"
PROMPT = "first_prompt.md"
SESSIONS = "sessions"

# Template markers left unfilled: "<...>" placeholders and the literal date pattern.
PLACEHOLDER = re.compile(r"<[^<>\n]{3,}>|YYYY-MM-DD")


def utc_now():
    return dt.datetime.now(dt.timezone.utc)


def stamp(t=None):
    return (t or utc_now()).strftime("%Y-%m-%d %H:%MZ")


def read_hook_input():
    """Hook input from stdin as a dict; anything else (empty, not JSON, not an object) becomes {}."""
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except (ValueError, UnicodeDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def git(root, *args):
    try:
        r = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def project_root(start=None):
    """CLAUDE_PROJECT_DIR if set, else the git top level of start (or cwd), else start itself."""
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return Path(env)
    base = Path(start) if isinstance(start, str) and start else Path.cwd()
    top = git(base, "rev-parse", "--show-toplevel")
    return Path(top) if top else base


def state_dir(root):
    return Path(root) / STATE_DIR


def session_file(root, session_id):
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", str(session_id))[:100] or "unknown"
    return state_dir(root) / SESSIONS / f"{safe}.json"


def read_text(path):
    """(text, error): text is None when the file is missing or unreadable; error names why."""
    try:
        return Path(path).read_text(encoding="utf-8"), None
    except FileNotFoundError:
        return None, "missing"
    except (OSError, UnicodeDecodeError) as e:
        return None, type(e).__name__


def section(text, title):
    """Body of a '## title' section (case-insensitive), up to the next '## ' heading; None when absent."""
    m = re.search(r"^##\s+" + re.escape(title) + r"\s*$(.*?)(?=^##\s|\Z)", text or "", re.M | re.S | re.I)
    return m.group(1).strip() if m else None


def fingerprint(root):
    """What a snapshot is valid for: git head plus hashes of STATE.md and DECISIONS.md."""
    root = Path(root)
    fp = {"head": git(root, "rev-parse", "HEAD") or ""}
    for key, name in (("state", "docs/STATE.md"), ("decisions", "docs/DECISIONS.md")):
        try:
            fp[key] = hashlib.sha256((root / name).read_bytes()).hexdigest()[:16]
        except OSError:
            fp[key] = ""
    return fp


def snapshot_id(fp, created):
    return hashlib.sha256((json.dumps(fp, sort_keys=True) + created).encode()).hexdigest()[:8]


def build_prompt(root, snap_id, problems):
    """First prompt text from the current STATE.md. The per-session acknowledgement line is appended by
    first_prompt.py, because one snapshot can be restored into several sessions."""
    state, _ = read_text(Path(root) / "docs/STATE.md")
    first = section(state, "First action") or "(no first action recorded)"
    goal = section(state, "Current goal") or "(no current goal recorded)"
    head = git(root, "log", "-1", "--format=%h %s") or "(no commits)"
    warn = ""
    if problems:
        warn = "\n## Warning: state was not fully ready when this was written\n" + "\n".join(f"- {p}" for p in problems) + "\n"
    return f"""# Compaction happened. Continue from here.

Snapshot {snap_id}, written {stamp()}, git head: {head}
{warn}
## First action
{first}

## Current goal
{goal}

## Before acting
1. Read docs/STATE.md, the newest entries of docs/DECISIONS.md, and docs/PROGRESS.md.
2. Run the acknowledgement command at the end of this prompt.
3. Do not retell the old conversation and do not search for it: what is needed is in the files above.
"""


def write_snapshot(root, problems, trigger, session_id=None):
    """Write .continuity/snapshot.json and first_prompt.md; returns the snapshot dict. Raises OSError on failure."""
    created = utc_now().isoformat()
    fp = fingerprint(root)
    snap = {
        "id": snapshot_id(fp, created),
        "created": created,
        "trigger": trigger,
        "session_id": session_id,
        "fingerprint": fp,
        "problems": problems,
    }
    d = state_dir(root)
    d.mkdir(parents=True, exist_ok=True)
    (d / PROMPT).write_text(build_prompt(root, snap["id"], problems), encoding="utf-8")
    (d / SNAPSHOT).write_text(json.dumps(snap, indent=2), encoding="utf-8")
    return snap


def new_token():
    """Acknowledgement token: one per session and per restore."""
    return secrets.token_hex(4)
