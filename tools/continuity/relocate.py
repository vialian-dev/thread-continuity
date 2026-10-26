#!/usr/bin/env python3
"""Readiness check before compaction. Writes FIRST_PROMPT.md when everything the thread knows is on disk and in git.

Run it before /compact (or let your assistant run it when context gets full). It answers one question:
if the conversation were wiped right now, could the thread continue from the files alone?

Checks:
  T  every truth file exists and is not empty
  F  docs/STATE.md has a "## First action" section whose first line starts with today's date (YYYY-MM-DD)
  G  git working tree is clean (everything committed)
  P  nothing unpushed (skipped when the branch has no upstream)

Exit 0 and "RESULT: ready for compaction" when all pass; otherwise exit 1 and the list of what to fix.
"""
import argparse
import datetime as dt
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import FIRST_PROMPT, TRUTH_FILES, git, project_root, utc_now  # noqa: E402


def section(text, title):
    """Body of a '## title' section (case-insensitive), up to the next '## ' heading."""
    m = re.search(r"^##\s+" + re.escape(title) + r"\s*$(.*?)(?=^##\s|\Z)", text, re.M | re.S | re.I)
    return m.group(1).strip() if m else None


def checks(root, today=None):
    root = Path(root)
    days = today or {utc_now().date().isoformat(), dt.date.today().isoformat()}
    problems = []
    for name in TRUTH_FILES:
        p = root / name
        if not p.is_file() or not p.read_text(encoding="utf-8").strip():
            problems.append(f"T  {name} is missing or empty")
    state = root / "docs/STATE.md"
    first = None
    if state.is_file():
        first = section(state.read_text(encoding="utf-8"), "First action")
    if not first:
        problems.append("F  docs/STATE.md has no '## First action' section")
    elif not any(first.splitlines()[0].startswith(d) for d in days):
        problems.append("F  '## First action' is not dated today (first line must start with YYYY-MM-DD)")
    status = git(root, "status", "--porcelain")
    if status is None:
        problems.append("G  not a git repository (the truth set must live in git)")
    elif status:
        problems.append(f"G  uncommitted changes: {len(status.splitlines())} file(s)")
    elif git(root, "rev-parse", "--abbrev-ref", "@{u}"):
        ahead = git(root, "rev-list", "--count", "@{u}..HEAD")
        if ahead and ahead != "0":
            problems.append(f"P  {ahead} commit(s) not pushed")
    return problems


def build_prompt(root):
    root = Path(root)
    state = (root / "docs/STATE.md").read_text(encoding="utf-8")
    first = section(state, "First action") or "(no first action recorded)"
    goal = section(state, "Current goal") or "(no current goal recorded)"
    head = git(root, "log", "-1", "--format=%h %s") or "(no commits)"
    stamp = utc_now().strftime("%Y-%m-%d %H:%MZ")
    return f"""# Compaction happened. Continue from here.

Written by tools/continuity/relocate.py at {stamp}, git head: {head}

## First action
{first}

## Current goal
{goal}

## Before acting
1. Read docs/STATE.md, docs/DECISIONS.md (newest entries first), docs/PROGRESS.md.
2. Run: python tools/continuity/ack.py
3. Do not retell the old conversation and do not search for it: everything needed is in the files above.
"""


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=None)
    a = ap.parse_args(argv)
    root = a.root or project_root()
    problems = checks(root)
    if problems:
        print("NOT READY — fix, commit, push, run again:")
        for p in problems:
            print("  " + p)
        return 1
    (Path(root) / FIRST_PROMPT).write_text(build_prompt(root), encoding="utf-8")
    print(f"{FIRST_PROMPT} written. Commit it, then compact.")
    print("RESULT: ready for compaction")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
