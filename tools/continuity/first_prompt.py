#!/usr/bin/env python3
"""SessionStart hook (matcher "compact"): put FIRST_PROMPT.md into the same thread right after compaction.

Claude Code runs SessionStart hooks after compaction with matcher value "compact" and adds
hookSpecificOutput.additionalContext to the model's context; systemMessage is shown to the user
(https://code.claude.com/docs/en/hooks). The hook also raises a flag that tools/continuity/ack.py clears,
so guard.py can tell whether the thread actually read the prompt.
Never fails the session: always exit 0.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import FIRST_PROMPT, pending_flag, project_root, utc_now  # noqa: E402

HEADER = (
    "[thread-continuity: first prompt after compaction, inserted by the SessionStart(compact) hook]\n"
    "Read this prompt and the files it names, then run: python tools/continuity/ack.py\n\n"
)


def main():
    try:
        sys.stdin.read()
    except Exception:  # noqa: BLE001 — hook input is informational here
        pass
    root = project_root()
    try:
        text = (root / FIRST_PROMPT).read_text(encoding="utf-8")
    except OSError as error:
        text = (f"{FIRST_PROMPT} not readable ({type(error).__name__}). "
                "Read docs/STATE.md (section '## First action') and docs/DECISIONS.md before acting.")
    out = {
        "systemMessage": "thread-continuity: the first prompt is already in the thread. Say 'continue'.",
        "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": HEADER + text},
    }
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False))
    try:
        flag = pending_flag(root)
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.write_text(utc_now().isoformat(), encoding="utf-8")
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
