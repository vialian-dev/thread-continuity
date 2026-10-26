"""Readiness checks shared by relocate.py (manual) and snapshot.py (PreCompact hook).

Each check returns a problem line or nothing. What the checks prove is narrow and stated in README "Limitations":
files exist and are filled in, the first action is dated today, git is committed and pushed.
They cannot judge whether the content is correct or complete. File and section names come from continuity.json.
"""
from pathlib import Path

from common import PLACEHOLDER, STATE_DIR, dated_today, git, load_config, read_text, section


def check_config(root):
    _, err = load_config(root)
    return [f"C  {err}"] if err else []


def check_files(root):
    cfg, _ = load_config(root)
    problems = []
    for name in cfg["truth_files"]:
        text, err = read_text(Path(root) / name)
        if text is None:
            problems.append(f"T  {name} {err}")
        elif not text.strip():
            problems.append(f"T  {name} is empty")
    return problems


def check_state(root, days=None):
    cfg, _ = load_config(root)
    name = cfg["state_file"]
    text, _ = read_text(Path(root) / name)
    if text is None:
        return [] if name in cfg["truth_files"] else [f"T  {name} not readable"]
    problems = []
    for title in (cfg["goal_section"], cfg["first_action_section"]):
        body = section(text, title)
        if not body:
            problems.append(f"S  {name} has no '{title}' section")
        elif PLACEHOLDER.search(body):
            problems.append(f"S  '{title}' still contains a template placeholder (<...> or YYYY-MM-DD)")
    first = section(text, cfg["first_action_section"])
    if first and not dated_today(first.splitlines()[0], cfg["date_formats"], days):
        problems.append(f"F  '{cfg['first_action_section']}' is not dated today (its first line must contain today's "
                        f"date as {' or '.join(cfg['date_formats'])})")
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
    return check_config(root) + check_files(root) + check_state(root) + check_git(root, no_remote)
