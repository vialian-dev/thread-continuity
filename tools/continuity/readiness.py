"""Readiness checks shared by relocate.py (manual) and snapshot.py (PreCompact hook).

Each check returns a problem line or nothing. What the checks prove is narrow and stated in README "Limitations":
files exist and are filled in, the first action is dated today, git is committed and pushed.
They cannot judge whether the content is correct or complete.
"""
import datetime as dt
from pathlib import Path

from common import PLACEHOLDER, STATE_DIR, TRUTH_FILES, git, read_text, section, utc_now

FILLED_SECTIONS = ("Current goal", "First action")


def check_files(root):
    problems = []
    for name in TRUTH_FILES:
        text, err = read_text(Path(root) / name)
        if text is None:
            problems.append(f"T  {name} {err}")
        elif not text.strip():
            problems.append(f"T  {name} is empty")
    return problems


def check_state(root, today=None):
    text, _ = read_text(Path(root) / "docs/STATE.md")
    if text is None:
        return []  # reported by check_files
    problems = []
    days = today or {utc_now().date().isoformat(), dt.date.today().isoformat()}
    for title in FILLED_SECTIONS:
        body = section(text, title)
        if not body:
            problems.append(f"S  docs/STATE.md has no '## {title}' section")
        elif PLACEHOLDER.search(body):
            problems.append(f"S  '## {title}' still contains a template placeholder (<...> or YYYY-MM-DD)")
    first = section(text, "First action")
    if first and not any(first.splitlines()[0].startswith(d) for d in days):
        problems.append("F  '## First action' is not dated today (its first line must start with YYYY-MM-DD)")
    return problems


def check_git(root, no_remote=False):
    status = git(root, "status", "--porcelain", "--", ".", f":(exclude){STATE_DIR}")
    if status is None:
        return ["G  not a git repository (the truth set must live in git)"]
    if status:
        return [f"G  uncommitted changes: {len(status.splitlines())} path(s)"]
    if not git(root, "rev-parse", "--abbrev-ref", "@{u}"):
        return [] if no_remote else ["P  branch has no upstream; push it, or pass --no-remote to accept local-only state"]
    ahead = git(root, "rev-list", "--count", "@{u}..HEAD")
    if ahead is None:
        return ["P  could not compare with upstream"]
    return [f"P  {ahead} commit(s) not pushed"] if ahead != "0" else []


def problems(root, no_remote=False):
    return check_files(root) + check_state(root) + check_git(root, no_remote)
