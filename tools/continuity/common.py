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

CONFIG_FILE = "continuity.json"
DEFAULTS = {
    "truth_files": ["docs/STATE.md", "docs/DECISIONS.md", "docs/PROGRESS.md", "docs/BACKLOG.md", "docs/LESSONS.md"],
    "state_file": "docs/STATE.md",
    "decisions_file": "docs/DECISIONS.md",
    "decisions_attachments": [],
    "goal_section": "Current goal",
    "first_action_section": "First action",
    "date_formats": ["%Y-%m-%d"],
    "read_first": ["docs/STATE.md", "docs/DECISIONS.md (newest entries)", "docs/PROGRESS.md"],
}
STATE_DIR = ".continuity"
SNAPSHOT = "snapshot.json"
PROMPT = "first_prompt.md"
SESSIONS = "sessions"

# Template markers left unfilled: "<...>" placeholders and the literal date pattern.
# "<" must be followed directly by a letter, so "quota < 99 %, ... ->" is not taken for a placeholder.
PLACEHOLDER = re.compile(r"<[^\W\d_][^<>\n]{2,}>|YYYY-MM-DD")


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


def load_config(root):
    """(config, error): DEFAULTS overlaid with continuity.json from the project root, if present.

    An unknown key or a value of the wrong type is an error, not a silent fallback: a typo would otherwise
    point every check at the wrong file."""
    cfg = {k: (list(v) if isinstance(v, list) else v) for k, v in DEFAULTS.items()}
    text, err = read_text(Path(root) / CONFIG_FILE)
    if text is None:
        return cfg, None if err == "missing" else f"{CONFIG_FILE} not readable ({err})"
    try:
        loaded = json.loads(text)
    except ValueError as e:
        return cfg, f"{CONFIG_FILE} is not valid JSON ({e})"
    if not isinstance(loaded, dict):
        return cfg, f"{CONFIG_FILE} must be a JSON object"
    unknown = sorted(set(loaded) - set(DEFAULTS))
    if unknown:
        return cfg, f"{CONFIG_FILE}: unknown keys {unknown}"
    for k, v in loaded.items():
        want = list if isinstance(DEFAULTS[k], list) else str
        if not isinstance(v, want) or (want is list and not all(isinstance(x, str) for x in v)):
            return cfg, f"{CONFIG_FILE}: {k} must be a {'list of strings' if want is list else 'string'}"
        cfg[k] = v
    return cfg, None


def section(text, title):
    """Body of the first Markdown heading (any level 1-6) whose text starts with `title` (case-insensitive),
    up to the next heading of the same or a higher level; None when absent."""
    for m in re.finditer(r"^(#{1,6})[ \t]+(.+?)[ \t]*$", text or "", re.M):
        if not m.group(2).lower().startswith(title.lower()):
            continue
        level = len(m.group(1))
        rest = text[m.end():]
        end = re.search(r"^#{1," + str(level) + r"}[ \t]", rest, re.M)
        return (rest[:end.start()] if end else rest).strip()
    return None


def dated_today(line, formats, days=None):
    """True when `line` contains today's date (UTC or local) in one of `formats`."""
    days = days or {utc_now().date(), dt.date.today()}
    return any(d.strftime(f) in line for d in days for f in formats)


def fingerprint(root):
    """What a snapshot is valid for: git head plus hashes of the state file and the decisions file."""
    root = Path(root)
    cfg, _ = load_config(root)
    fp = {"head": git(root, "rev-parse", "HEAD") or ""}
    for key, name in (("state", cfg["state_file"]), ("decisions", cfg["decisions_file"])):
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
    cfg, _ = load_config(root)
    state, _ = read_text(Path(root) / cfg["state_file"])
    first = section(state, cfg["first_action_section"]) or "(no first action recorded)"
    goal = section(state, cfg["goal_section"]) or "(no current goal recorded)"
    reading = ", ".join(cfg["read_first"])
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
1. Read: {reading}.
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
