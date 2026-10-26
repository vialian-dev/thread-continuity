#!/usr/bin/env python3
"""PreCompact hook: take a snapshot of the thread's state right before any compaction, manual or automatic.

Claude Code runs PreCompact with matcher "manual" (/compact) or "auto" and passes session_id, transcript_path and
trigger on stdin (https://code.claude.com/docs/en/hooks#precompact). The snapshot records the git head and hashes of
docs/STATE.md and docs/DECISIONS.md, plus any readiness problems found; first_prompt.py later refuses to present a
snapshot whose fingerprint no longer matches the files.

Never blocks automatic compaction (blocking it can fail the request that triggered it). Blocks a manual /compact only
when CONTINUITY_BLOCK_MANUAL=1 and problems were found (exit 2, the reason is shown to the user).
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import project_root, read_hook_input, utc_now, write_snapshot  # noqa: E402
import decisions  # noqa: E402
import readiness  # noqa: E402


def main():
    hook = read_hook_input()
    root = project_root(hook.get("cwd"))
    trigger = hook.get("trigger") if hook.get("trigger") in ("manual", "auto") else "unknown"
    found = readiness.problems(root, os.environ.get("CONTINUITY_NO_REMOTE") == "1")
    r = decisions.check(root, hook.get("transcript_path"), utc_now())
    if r["status"] == "fix":
        found.append(f"D  {r['missing']} user message(s) not recorded verbatim in docs/DECISIONS.md")
    elif r["status"] == "unknown":
        found.append(f"D  could not check decisions: {r['reason']}")
    if found and trigger == "manual" and os.environ.get("CONTINUITY_BLOCK_MANUAL") == "1":
        print("thread-continuity: compaction blocked, state not ready:\n  " + "\n  ".join(found), file=sys.stderr)
        return 2
    try:
        write_snapshot(root, found, trigger, hook.get("session_id"))
    except OSError as e:
        # PreCompact output is not shown to the model; first_prompt.py reports the missing snapshot after compaction.
        print(f"thread-continuity: snapshot not written ({type(e).__name__})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001: a broken hook must not break compaction
        print(f"thread-continuity: snapshot hook failed ({type(e).__name__}: {e})", file=sys.stderr)
        raise SystemExit(0)
