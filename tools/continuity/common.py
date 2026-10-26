"""Shared paths and helpers for the thread-continuity tools."""
import datetime as dt
import os
import subprocess
from pathlib import Path

TRUTH_FILES = (
    "docs/STATE.md",
    "docs/DECISIONS.md",
    "docs/PROGRESS.md",
    "docs/BACKLOG.md",
    "docs/LESSONS.md",
)
FIRST_PROMPT = "FIRST_PROMPT.md"
STATE_DIR = ".continuity"
PENDING = "first_prompt_pending"


def project_root(start=None):
    """CLAUDE_PROJECT_DIR if set, else the git top level of start (or cwd), else start itself."""
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return Path(env)
    base = Path(start or Path.cwd())
    top = git(base, "rev-parse", "--show-toplevel")
    return Path(top) if top else base


def git(root, *args):
    try:
        r = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def utc_now():
    return dt.datetime.now(dt.timezone.utc)


def pending_flag(root):
    return Path(root) / STATE_DIR / PENDING
