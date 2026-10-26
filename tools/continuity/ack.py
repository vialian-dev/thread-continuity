#!/usr/bin/env python3
"""Acknowledge the first prompt after compaction: python tools/continuity/ack.py <token>

The token is created per session and per restore; it is printed in that session's first prompt and stored in that
session's record. Presenting it changes exactly one record. It proves the token was presented, not that the prompt
was read or understood (see README "Limitations").
Exit 0 acknowledged or nothing pending, 1 wrong token, 2 usage error.
"""
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # no __pycache__ in the project tree (it would make git "dirty")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import SESSIONS, project_root, state_dir, utc_now  # noqa: E402


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: python tools/continuity/ack.py <token from the first prompt>")
        return 2
    want = args[0].strip()
    pending = 0
    for f in sorted((state_dir(project_root()) / SESSIONS).glob("*.json")):
        try:
            rec = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeDecodeError):
            continue
        if not isinstance(rec, dict) or not rec.get("pending"):
            continue
        pending += 1
        if rec.get("token") == want:
            rec.update(pending=False, acknowledged=utc_now().isoformat())
            f.write_text(json.dumps(rec), encoding="utf-8")
            print(f"first prompt acknowledged ({f.stem})")
            return 0
    if pending:
        print(f"token {want} does not match any pending first prompt; read your first prompt again")
        return 1
    print("nothing to acknowledge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
