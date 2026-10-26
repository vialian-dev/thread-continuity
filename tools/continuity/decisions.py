"""Are the user's messages recorded verbatim in docs/DECISIONS.md? Shared by guard.py and snapshot.py.

Rule (a heuristic, stated as one):
  - a message counts as recorded when its full text, whitespace-normalised and with secret-like values replaced by
    [REDACTED], appears in DECISIONS.md;
  - a message shorter than SHORT characters ("yes", "go") must also share its entry with its own UTC time HH:MM,
    otherwise any "yes" anywhere would match;
  - only messages of the last WINDOW_H hours are checked; messages younger than FRESH_S seconds are "record now",
    not gaps (the assistant has not had a turn to write them yet).
Result status: "ok" (all checked messages recorded), "nothing" (no user messages in the window), "fix" (gaps),
"unknown" (could not check: no transcript, no log, unreadable lines).
"""
import datetime as dt
import json
import os
import re
from pathlib import Path

WINDOW_H = 36
FRESH_S = 180
SHORT = 20

WRAPPERS = (
    "command-name", "command-message", "command-args", "local-command-stdout", "local-command-stderr",
    "local-command-caveat", "system-reminder", "task-notification", "bash-input", "bash-stdout", "bash-stderr",
    "user-prompt-submit-hook",
)
COMPACTION_SUMMARY = "This session is being continued from a previous conversation"
PASTED = re.compile(r"<pasted_content[^>]*>.*?</pasted_content[^>]*>", re.S)
SECRET = re.compile(
    r"sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|xox[abprs]-[A-Za-z0-9-]{10,}"
    r"|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"
)


def norm(text):
    return re.sub(r"\s+", " ", SECRET.sub("[REDACTED]", text)).strip()


def is_wrapper(text):
    t = text.lstrip()
    return t.startswith(COMPACTION_SUMMARY) or any(t.startswith("<" + w) for w in WRAPPERS)


def parse_ts(value):
    try:
        t = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def text_of(content):
    if isinstance(content, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
            return None
        content = " ".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return content if isinstance(content, str) else None


TS = re.compile(rb'"timestamp":\s*"([^"]+)"')
SEEK_MIN = int(os.environ.get("CONTINUITY_SEEK_MIN", 16 * 1024 * 1024))


def _ts_at(f, pos):
    """Timestamp of the first complete line at or after byte pos, or None."""
    f.seek(pos)
    if pos:
        f.readline()
    for _ in range(50):
        line = f.readline()
        if not line:
            return None
        m = TS.search(line)
        if m:
            return parse_ts(m.group(1).decode("ascii", "replace"))
    return None


def window_lines(transcript, since):
    """Lines of the transcript from roughly `since` on. Large files are entered by binary search on timestamps
    (entries are appended in time order), so the cost does not grow with the whole history."""
    with open(transcript, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        lo = 0
        if size > SEEK_MIN:
            lo, hi = 0, size
            while hi - lo > max(65536, size // 256):
                mid = (lo + hi) // 2
                t = _ts_at(f, mid)
                if t is not None and t < since:
                    lo = mid
                else:
                    hi = mid
        f.seek(lo)
        if lo:
            f.readline()
        for raw in f:
            yield raw.decode("utf-8", "replace")


def user_messages(transcript, since):
    """(messages, unreadable): messages are (utc time, text) typed by the user since `since`.

    Only lines that can hold a user message are parsed. A broken line counts as unreadable, except an unterminated
    last line (no newline yet), which Claude Code may still be writing. Repeated messages are kept: two "yes" at
    different times are two messages; only an exact repeat (same time, same text) is dropped.
    """
    out, seen, unreadable = [], set(), 0
    for line in window_lines(transcript, since):
        if not line.strip():
            continue
        complete = line.endswith("\n")
        if '"user"' not in line and '"attachment"' not in line:
            body = line.strip()
            if complete and not (body.startswith("{") and body.endswith("}")):
                unreadable += 1
            continue
        try:
            e = json.loads(line)
        except ValueError:
            if complete:
                unreadable += 1
            continue
        if not isinstance(e, dict):
            unreadable += 1
            continue
        if e.get("type") == "attachment":
            a = e.get("attachment") or {}
            if not isinstance(a, dict) or (a.get("origin") or {}).get("kind") != "human":
                continue
            text = text_of(a.get("prompt"))
        elif e.get("type") == "user" and not e.get("isMeta") and e.get("toolUseResult") is None:
            text = text_of((e.get("message") or {}).get("content"))
        else:
            continue
        if not text:
            continue
        own = PASTED.sub(" ", text).strip()
        if not own or is_wrapper(own):
            continue
        t = parse_ts(e.get("timestamp"))
        if t is None:
            unreadable += 1
            continue
        if t >= since and (t, own) not in seen:
            seen.add((t, own))
            out.append((t, own))
    return out, unreadable


def last_compaction(transcript, since=None):
    """UTC time of the newest compaction boundary in the transcript, or None.

    Relies on the transcript's "system" entries with subtype "compact_boundary" (observed in Claude Code
    transcripts; the transcript format is not a documented API).
    """
    last = None
    for line in window_lines(transcript, since or dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)):
        if '"compact_boundary"' not in line:
            continue
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if isinstance(e, dict) and e.get("subtype") == "compact_boundary":
            t = parse_ts(e.get("timestamp"))
            if t and (last is None or t > last):
                last = t
    return last


def entries(log_text):
    """DECISIONS.md split into entries (paragraphs / list items), each normalised."""
    parts = re.split(r"\n(?=\s*[-*] )|\n\s*\n", log_text)
    return [norm(p) for p in parts if p.strip()]


def is_recorded(t, text, log_norm, log_entries):
    n = norm(text)
    if len(n) >= SHORT:
        return n in log_norm
    hhmm = t.strftime("%H:%M")
    return any(n in e and hhmm in e for e in log_entries)


def check(root, transcript, now, grace=True):
    """dict(status, missing, fresh, checked, unreadable, reason).

    grace=False (before compaction): a message not yet recorded is a gap however young it is.
    """
    res = {"status": "unknown", "missing": 0, "fresh": 0, "checked": 0, "unreadable": 0, "reason": ""}
    if not transcript:
        res["reason"] = "no transcript path in hook input"
        return res
    if not Path(str(transcript)).is_file():
        # The first message of a new session arrives before Claude Code has written the transcript file.
        res["reason"] = "transcript not written yet (new session)"
        if grace:
            res["status"] = "nothing"
        return res
    try:
        log = (Path(root) / "docs/DECISIONS.md").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        res["reason"] = f"docs/DECISIONS.md not readable ({type(e).__name__})"
        return res
    try:
        msgs, res["unreadable"] = user_messages(transcript, now - dt.timedelta(hours=WINDOW_H))
    except OSError as e:
        res["reason"] = f"transcript not readable ({type(e).__name__})"
        return res
    log_norm, log_entries = norm(log), entries(log)
    for t, text in msgs:
        res["checked"] += 1
        if is_recorded(t, text, log_norm, log_entries):
            continue
        if grace and (now - t).total_seconds() < FRESH_S:
            res["fresh"] += 1
        else:
            res["missing"] += 1
    if res["unreadable"]:
        res["reason"] = f"{res['unreadable']} transcript line(s) unreadable"
    if res["missing"]:
        res["status"] = "fix"
    elif res["unreadable"]:
        res["status"] = "unknown"
    elif not msgs:
        res["status"] = "nothing"
    else:
        res["status"] = "ok"
    return res


def secrets_in(root):
    """Number of secret-like values in docs/*.md (they must be recorded as [REDACTED])."""
    n = 0
    for p in sorted((Path(root) / "docs").glob("*.md")):
        try:
            n += len(SECRET.findall(p.read_text(encoding="utf-8", errors="replace")))
        except OSError:
            continue
    return n
