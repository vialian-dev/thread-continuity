#!/usr/bin/env python3
"""Acknowledge the first prompt after compaction: python tools/continuity/ack.py <snapshot-id>

The id appears only in the first prompt, so acknowledging requires having seen it. It proves the prompt was seen,
not that it was understood. Every pending session record with this id is acknowledged; two sessions compacted
from the same snapshot share it (see README "Limitations").
Exit 0 acknowledged or nothing pending, 1 wrong id, 2 usage error.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import SESSIONS, project_root, state_dir, utc_now  # noqa: E402


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: python tools/continuity/ack.py <snapshot-id from the first prompt>")
        return 2
    want = args[0].strip()
    acked, other = 0, set()
    for f in sorted((state_dir(project_root()) / SESSIONS).glob("*.json")):
        try:
            rec = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(rec, dict) or not rec.get("pending"):
            continue
        if rec.get("snapshot_id") != want:
            other.add(str(rec.get("snapshot_id")))
            continue
        rec.update(pending=False, acknowledged=utc_now().isoformat())
        f.write_text(json.dumps(rec), encoding="utf-8")
        acked += 1
    if acked:
        print(f"first prompt acknowledged (snapshot {want})")
        return 0
    if other:
        print(f"snapshot id {want} does not match the pending first prompt; read the first prompt again")
        return 1
    print("nothing to acknowledge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
