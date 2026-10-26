#!/usr/bin/env python3
"""UserPromptSubmit hook: one advisory line per user message about the thread's memory. It never blocks the prompt.

Claude Code adds a UserPromptSubmit hook's stdout to the model's context and passes session_id and transcript_path
on stdin (https://code.claude.com/docs/en/hooks#userpromptsubmit).

  A  first prompt after compaction: "ok" (acknowledged or no compaction in the transcript), "FIX FIRST" (pending for
     this session), "wait" (session registered by session_start.py in the last 10 minutes, transcript not there yet),
     "?" (cannot tell: no session id, unreadable state, no transcript, or a compaction with no first-prompt record)
  D  user messages recorded verbatim in docs/DECISIONS.md (rules in decisions.py): ok / nothing to check / FIX / ?
  S  secret-like values in docs/*.md: shown only when found
Every check that cannot be measured prints "?" with the reason.
"""
import datetime as dt
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # no __pycache__ in the project tree (it would make git "dirty")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import SESSIONS, project_root, read_hook_input, session_file, stamp, state_dir, utc_now  # noqa: E402
import decisions  # noqa: E402


NEW_SESSION_S = 600


def load_record(root, session_id):
    """(record, problem): record is None when absent; problem names why it cannot be used."""
    f = session_file(root, session_id)
    try:
        rec = json.loads(f.read_text(encoding="utf-8")) if f.exists() else None
    except (OSError, ValueError, UnicodeDecodeError) as e:
        return None, f"session record unreadable: {type(e).__name__}"
    if rec is not None and not (isinstance(rec, dict) and isinstance(rec.get("pending"), bool)):
        return None, "session record malformed"
    return rec, None


def fresh_start(rec, now):
    """True when session_start.py registered this session as new within NEW_SESSION_S and it was never restored."""
    if not rec or rec.get("since") or rec.get("source") not in ("startup", "clear"):
        return False
    started = decisions.parse_ts(rec.get("started"))
    return started is not None and 0 <= (now - started).total_seconds() < NEW_SESSION_S


def check_ack(root, session_id, transcript, now):
    if not session_id:
        try:
            pending = sum(1 for f in (state_dir(root) / SESSIONS).glob("*.json")
                          if json.loads(f.read_text(encoding="utf-8")).get("pending"))
        except (OSError, ValueError, AttributeError):
            return "A ? (no session id; session records unreadable)"
        return f"A ? (no session id in hook input; {pending} pending in project)"
    rec, problem = load_record(root, session_id)
    if problem:
        return f"A ? ({problem})"
    if rec and rec["pending"]:
        return ("A FIX FIRST: first prompt after compaction not acknowledged; read it, then run "
                "python tools/continuity/ack.py <token from the prompt>")
    if not (transcript and Path(str(transcript)).is_file()):
        # Without the transcript a compaction cannot be ruled out: never "ok" here.
        if fresh_start(rec, now):
            return "A wait (session registered at start; transcript expected)"
        return "A ? (transcript unavailable: cannot rule out an unacknowledged compaction)"
    try:
        compacted = decisions.last_compaction(transcript, now - dt.timedelta(hours=decisions.WINDOW_H))
    except OSError:
        return "A ? (transcript unreadable)"
    if compacted:
        since = decisions.parse_ts(rec.get("since")) if rec else None
        if since is None or since < compacted - dt.timedelta(minutes=1):
            return f"A ? (compaction at {stamp(compacted)} but no first-prompt record for this session)"
    return "A ok"


def check_decisions(root, session_id, transcript, now):
    r = decisions.check(root, transcript, now)
    note = f"; ? {r['reason']}" if r["reason"] and r["status"] == "fix" else ""
    if r["status"] == "fix":
        return f"D FIX: {r['missing']} user message(s) not recorded verbatim in {r.get('file', 'the decisions file')}{note}"
    if r["status"] == "unknown":
        if r.get("file_missing") and session_id and fresh_start(load_record(root, session_id)[0], now):
            return "D wait (session registered at start; transcript expected)"
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
    for name, fn in (("A", lambda: check_ack(root, hook.get("session_id"), transcript, now)),
                     ("D", lambda: check_decisions(root, hook.get("session_id"), transcript, now))):
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
