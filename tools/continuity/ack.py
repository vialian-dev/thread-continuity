#!/usr/bin/env python3
"""Acknowledge that the first prompt after compaction was read (clears the flag raised by first_prompt.py)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import pending_flag, project_root  # noqa: E402


def main():
    try:
        pending_flag(project_root()).unlink()
    except FileNotFoundError:
        print("nothing to acknowledge")
    else:
        print("first prompt acknowledged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
