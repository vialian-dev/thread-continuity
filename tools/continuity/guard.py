#!/usr/bin/env python3
"""UserPromptSubmit hook: one advisory line per user message about the thread's memory. It never blocks the prompt.

Claude Code adds a UserPromptSubmit hook's stdout to the model's context and passes session_id and transcript_path
on stdin (https://code.claude.com/docs/en/hooks#userpromptsubmit).

  A  first prompt after compaction: "ok" (acknowledged or no compaction), "FIX FIRST" (pending for this session),
     "?" (cannot tell: no session id, unreadable state, or a compaction with no first-prompt record)
  D  user messages recorded verbatim in docs/DECISIONS.md (rules in decisions.py): ok / nothing to check / FIX / ?
  S  secret-like values in docs/*.md: shown only when found
Every check that cannot be measured prints "?" with the reason.
"""
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import SESSIONS, project_root, read_hook_input, session_file, stamp, state_dir, utc_now  # noqa: E402
import decisions  # noqa: E402


def check_ack(root, session_id, transcript):
    if not session_id:
        try:
            pending = sum(1 for f in (state_dir(root) / SESSIONS).glob("*.json")
                          if json.loads(f.read_text(encoding="utf-8")).get("pending"))
        except (OSError, ValueError, AttributeError):
            return "A ? (no session id; session records unreadable)"
        return f"A ? (no session id in hook input; {pending} pending in project)"
    f = session_file(root, session_id)
    try:
        rec = json.loads(f.read_text(encoding="utf-8")) if f.exists() else None
    except (OSError, ValueError, UnicodeDecodeError) as e:
        return f"A ? (session record unreadable: {type(e).__name__})"
    if isinstance(rec, dict) and rec.get("pending"):
        return (f"A FIX FIRST: first prompt after compaction not acknowledged; read it, then run "
                f"python tools/continuity/ack.py <snapshot id from the prompt>")
    compacted = None
    if transcript and Path(str(transcript)).is_file():
        try:
            compacted = decisions.last_compaction(
                transcript, utc_now() - dt.timedelta(hours=decisions.WINDOW_H))
        except OSError:
            return "A ? (transcript unreadable)"
    if compacted:
        since = decisions.parse_ts((rec or {}).get("since")) if isinstance(rec, dict) else None
        if since is None or since < compacted - dt.timedelta(minutes=1):
            return f"A ? (compaction at {stamp(compacted)} but no first-prompt record for this session)"
    return "A ok"


def check_decisions(root, transcript, now):
    r = decisions.check(root, transcript, now)
    note = f"; ? {r['reason']}" if r["reason"] and r["status"] == "fix" else ""
    if r["status"] == "fix":
        return f"D FIX: {r['missing']} user message(s) not recorded verbatim in docs/DECISIONS.md{note}"
    if r["status"] == "unknown":
        return f"D ? ({r['reason']})"
    if r["status"] == "nothing":
        return f"D nothing to check (no user messages in the last {decisions.WINDOW_H} h)"
    extra = "; record the new user message now" if r["fresh"] else ""
    return f"D ok ({r['checked']} checked){extra}"


def main():
    hook = read_hook_input()
    root = project_root(hook.get("cwd"))
    now = utc_now()
    transcript = hook.get("transcript_path")
    parts = []
    for name, fn in (("A", lambda: check_ack(root, hook.get("session_id"), transcript)),
                     ("D", lambda: check_decisions(root, transcript, now))):
        try:
            parts.append(fn())
        except Exception as e:  # noqa: BLE001: an advisory hook reports, it does not crash
            parts.append(f"{name} ? ({type(e).__name__})")
    n = decisions.secrets_in(root)
    if n:
        parts.append(f"S WARN: {n} secret-like value(s) in docs/*.md; replace with [REDACTED] and rotate them")
    sys.stdout.reconfigure(encoding="utf-8")
    print(f"CONTINUITY GUARD {stamp(now)}: " + " | ".join(parts))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        print(f"CONTINUITY GUARD ? (guard failed: {type(e).__name__})")
        raise SystemExit(0)
