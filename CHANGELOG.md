# Changelog

## 0.2.0 (2026-10-26)

Fixes from the first external review (every case below has a regression test):

- Decisions: a message counts as recorded only when its **full** text is in `DECISIONS.md` (was: first 60 characters).
  Messages shorter than 20 characters must also carry their own UTC time in the same entry.
- Decisions: only known Claude Code wrappers are skipped (was: anything starting with `<`). Unreadable transcript lines
  give `?`, not `ok`. Results are `ok` / `nothing to check` / `FIX` / `?`.
- Readiness: template placeholders, a missing upstream (unless `--no-remote`) and unpushed commits give NOT READY.
  The snapshot lives in the untracked `.continuity/`, so READY leaves the tree clean.
- New `PreCompact` hook (`snapshot.py`) takes the snapshot before every compaction, manual or automatic.
- First prompt: a snapshot that no longer matches git head, `STATE.md` and `DECISIONS.md` is rebuilt from the current
  files with a warning, never presented as current.
- Acknowledgement is per session and needs the snapshot id printed in the first prompt.
- Failures to write state are reported to the user and the model; the guard prints `?`, not `ok`.
- Malformed hook input, naive timestamps and undecodable files no longer crash a hook.
- Secret-like values in `docs/*.md` are flagged; the protocol says to record them as `[REDACTED]`.
- Large transcripts are entered by binary search on timestamps (408 MB transcript: 4.9 s -> 0.4 s per message).
- CI: GitHub Actions (Linux, Windows, macOS; Python 3.9 and 3.13) and GitLab CI.

## 0.1.0 (2026-10-26)

First version.
