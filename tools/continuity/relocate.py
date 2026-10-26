#!/usr/bin/env python3
"""Manual readiness check before /compact. Prints every check, then READY or NOT READY.

Checks:
  T  every truth file exists, is readable and not empty
  S  docs/STATE.md '## Current goal' and '## First action' exist and contain no template placeholders
  F  '## First action' starts with today's date (YYYY-MM-DD, UTC or local)
  G  git working tree is clean (the .continuity/ state directory is ignored)
  P  branch has an upstream and nothing is unpushed (--no-remote accepts a local-only repository)
  D  every user message is recorded in docs/DECISIONS.md (only with --transcript; the PreCompact hook runs it
     automatically because it receives the transcript path)
On READY it writes the snapshot (.continuity/snapshot.json and first_prompt.md, untracked).
Exit 0 ready, 1 not ready.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import project_root, utc_now, write_snapshot  # noqa: E402
import decisions  # noqa: E402
import readiness  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=None)
    ap.add_argument("--no-remote", action="store_true", help="accept a branch without upstream")
    ap.add_argument("--transcript", type=Path, default=None, help="session transcript (.jsonl) for check D")
    a = ap.parse_args(argv)
    root = a.root or project_root()
    found = readiness.problems(root, a.no_remote)
    checked = "T S F G" + (" (P skipped: --no-remote)" if a.no_remote else " P")
    if a.transcript:
        r = decisions.check(root, a.transcript, utc_now(), grace=False)
        checked += " D"
        if r["status"] == "fix":
            found.append(f"D  {r['missing']} user message(s) not recorded verbatim in docs/DECISIONS.md")
        elif r["status"] == "unknown":
            found.append(f"D  could not check decisions: {r['reason']}")
    sys.stdout.reconfigure(encoding="utf-8")
    if found:
        print("NOT READY. Fix, commit, push, run again:")
        for p in found:
            print("  " + p)
        print(f"Checked: {checked}")
        return 1
    try:
        snap = write_snapshot(root, [], "manual-check")
    except OSError as e:
        print(f"NOT READY: could not write the snapshot ({type(e).__name__}: {e})")
        return 1
    print(f"Checked: {checked}" + ("" if a.transcript else "; D not checked here (no --transcript)"))
    print(f"Snapshot {snap['id']} written to .continuity/")
    print("RESULT: ready for compaction")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
