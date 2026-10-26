#!/usr/bin/env python3
"""UserPromptSubmit hook: one line per user message — is the thread's memory being kept right now?

Claude Code adds the stdout of a UserPromptSubmit hook to the context and passes the transcript path on stdin
(https://code.claude.com/docs/en/hooks). The guard never blocks the prompt: always exit 0.

Checks:
  A  the first prompt after compaction was acknowledged (flag from first_prompt.py is cleared by ack.py)
  D  every user message of the last WINDOW_H hours is recorded verbatim in docs/DECISIONS.md
     (first 60 characters after whitespace normalisation); messages younger than FRESH_S are "record now", not gaps
A check that cannot be measured prints "?" with the reason; it never prints ok for it.
"""
import datetime as dt
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import pending_flag, project_root, utc_now  # noqa: E402

WINDOW_H = 36
FRESH_S = 180
PREFIX = 60


def norm(text):
    return re.sub(r"\s+", " ", text).strip()


def user_messages(transcript, since):
    """(timestamp, text) of messages the user typed; tool results and system/peer texts are skipped."""
    out = []
    for line in Path(transcript).read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("type") != "user" or d.get("isMeta"):
            continue
        content = (d.get("message") or {}).get("content")
        if isinstance(content, list):
            content = " ".join(c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text")
        if not isinstance(content, str) or not content.strip() or content.lstrip().startswith("<"):
            continue
        try:
            ts = dt.datetime.fromisoformat(d.get("timestamp", "").replace("Z", "+00:00"))
        except ValueError:
            continue
        if ts >= since:
            out.append((ts, content))
    return out


def check_decisions(root, transcript, now):
    if not transcript or not Path(transcript).is_file():
        return "D ? (no transcript path on stdin)"
    log = root / "docs/DECISIONS.md"
    if not log.is_file():
        return "D ? (docs/DECISIONS.md missing)"
    recorded = norm(log.read_text(encoding="utf-8"))
    missing = fresh = 0
    for ts, text in user_messages(transcript, now - dt.timedelta(hours=WINDOW_H)):
        if norm(text)[:PREFIX] in recorded:
            continue
        if (now - ts).total_seconds() < FRESH_S:
            fresh += 1
        else:
            missing += 1
    if missing:
        return f"D FIX: {missing} user message(s) not recorded verbatim in docs/DECISIONS.md"
    if fresh:
        return "D ok; record the new user message in docs/DECISIONS.md now"
    return "D ok"


def main():
    try:
        hook_input = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        hook_input = {}
    root = project_root(hook_input.get("cwd"))
    now = utc_now()
    parts = []
    if pending_flag(root).exists():
        parts.append("A FIX FIRST: first prompt after compaction not acknowledged — read FIRST_PROMPT.md, "
                     "then run python tools/continuity/ack.py")
    else:
        parts.append("A ok")
    try:
        parts.append(check_decisions(root, hook_input.get("transcript_path"), now))
    except OSError as error:
        parts.append(f"D ? ({type(error).__name__})")
    sys.stdout.reconfigure(encoding="utf-8")
    print(f"CONTINUITY GUARD {now.strftime('%Y-%m-%d %H:%MZ')}: " + " | ".join(parts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
