#!/usr/bin/env python3
"""SessionStart hook (matcher "compact"): put the first prompt into the same thread right after compaction.

Claude Code adds hookSpecificOutput.additionalContext to the model's context and shows systemMessage to the user
(https://code.claude.com/docs/en/hooks#sessionstart). Steps:
  1. load .continuity/snapshot.json (written by the PreCompact hook or relocate.py);
  2. if it is missing, unreadable or its fingerprint no longer matches git head + STATE.md + DECISIONS.md,
     rebuild the prompt from the current files and say so, instead of presenting a stale plan as current;
  3. record "first prompt pending" for this session_id with a fresh token printed only in this session's prompt
     (and in its record); ack.py <token> changes exactly that one record.
Any failure is reported in both the context and the user-visible message; the session itself is never failed.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (PROMPT, SNAPSHOT, fingerprint, new_token, project_root, read_hook_input, read_text,  # noqa: E402
                    session_file, state_dir, utc_now, write_snapshot)

HEADER = "[thread-continuity: first prompt after compaction, inserted by the SessionStart(compact) hook]\n\n"


def load_snapshot(root):
    """(snapshot, prompt_text, problem): problem is None when the snapshot is present and matches the files."""
    raw, err = read_text(state_dir(root) / SNAPSHOT)
    if raw is None:
        return None, None, f"no snapshot ({err})"
    try:
        snap = json.loads(raw)
    except ValueError:
        return None, None, "snapshot.json is not valid JSON"
    if not isinstance(snap, dict) or "id" not in snap:
        return None, None, "snapshot.json has no id"
    prompt, err = read_text(state_dir(root) / PROMPT)
    if prompt is None:
        return None, None, f"first_prompt.md {err}"
    if snap.get("fingerprint") != fingerprint(root):
        return None, None, f"snapshot {snap['id']} is stale: git head, STATE.md or DECISIONS.md changed after it"
    return snap, prompt, None


def main():
    hook = read_hook_input()
    root = project_root(hook.get("cwd"))
    session_id = hook.get("session_id") or "unknown"
    warnings = []
    snap, prompt, problem = load_snapshot(root)
    if problem:
        warnings.append(problem + "; prompt rebuilt from the current files")
        try:
            snap = write_snapshot(root, [problem], "rebuilt-after-compaction", session_id)
            prompt, _ = read_text(state_dir(root) / PROMPT)
        except OSError as e:
            warnings.append(f"state directory not writable ({type(e).__name__}); acknowledgement will not work")
            snap, prompt = None, None
    if prompt is None:
        prompt = ("No first prompt could be prepared. Read docs/STATE.md ('## First action'), the newest entries of "
                  "docs/DECISIONS.md and docs/PROGRESS.md before acting.\n")
    token = None
    if snap:
        token = new_token()
        try:
            f = session_file(root, session_id)
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps({"pending": True, "token": token, "snapshot_id": snap["id"],
                                     "since": utc_now().isoformat()}), encoding="utf-8")
        except OSError as e:
            token = None
            warnings.append(f"pending flag not saved ({type(e).__name__}); acknowledgement will not work, "
                            "the guard will report '?'")
    if token:
        prompt = prompt.rstrip() + f"\n\n## Acknowledge\nRun: python tools/continuity/ack.py {token}\n"
    context = HEADER + prompt
    if warnings:
        context = HEADER + "WARNINGS:\n" + "\n".join(f"- {w}" for w in warnings) + "\n\n" + prompt
    message = "thread-continuity: first prompt inserted into the thread. Say 'continue'."
    if warnings:
        message += " Warnings: " + "; ".join(warnings)
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps({"systemMessage": message,
                      "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context}},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001: report, never fail the session
        sys.stdout.reconfigure(encoding="utf-8")
        print(json.dumps({"systemMessage": f"thread-continuity: first prompt hook failed ({type(e).__name__}: {e})"}))
        raise SystemExit(0)
