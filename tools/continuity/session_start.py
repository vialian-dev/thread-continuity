#!/usr/bin/env python3
"""SessionStart hook (matchers "startup" and "clear"): register that this session started fresh.

The guard must not infer "new session" from a missing transcript file: a transcript can also be missing because it
was moved, deleted or not yet flushed. This hook records the start explicitly, so the guard can tell a new session
(no compaction possible yet) from an existing one whose transcript is unavailable (unknown).
Prints nothing (nothing is added to the context). Never fails the session: always exit 0.
"""
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # no __pycache__ in the project tree (it would make git "dirty")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import project_root, read_hook_input, session_file, utc_now  # noqa: E402


def main():
    hook = read_hook_input()
    source = hook.get("source")
    session_id = hook.get("session_id")
    if source not in ("startup", "clear") or not isinstance(session_id, str) or not session_id:
        return 0
    f = session_file(project_root(hook.get("cwd")), session_id)
    if f.exists():
        return 0  # never overwrite a record that may hold a pending first prompt
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"pending": False, "started": utc_now().isoformat(), "source": source}),
                     encoding="utf-8")
    except OSError as e:
        print(f"thread-continuity: session start not recorded ({type(e).__name__})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001: a broken hook must not break the session
        print(f"thread-continuity: session start hook failed ({type(e).__name__}: {e})", file=sys.stderr)
        raise SystemExit(0)
