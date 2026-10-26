# Changelog

## 0.2.0 (2026-10-26)

Fix from the fourth review:

- An unavailable transcript never gives `ok` or `nothing to check`: `wait` for a session registered in the last
  10 minutes, `?` otherwise, also for a registered or acknowledged session whose transcript disappeared.

Fix from the third review:

- A missing transcript no longer means "new session": a new session is registered by the `SessionStart(startup|clear)`
  hook `session_start.py`; otherwise a missing transcript gives `?`.
- README Limitations: transcript lag, and where automation ends and the human begins.

Fixes from the second review:

- Before compaction (PreCompact, `relocate.py --transcript`) there is no 180-second grace: every unrecorded message
  is a problem in the snapshot and the first prompt.
- Acknowledgement uses a fresh token per session and per restore; one `ack.py` call changes one record, also when
  two sessions are restored from the same snapshot.
- Repeated messages (two "yes" at different times) are checked separately.
- A broken, newline-terminated last transcript line gives `?`; only an unterminated tail is ignored.
- Guard: no session record and no transcript gives `A ?`; a malformed session record gives `A ?`.
- Found in a live `/compact` run in Claude Code 2.1.309: scripts wrote `__pycache__` into the project (made git
  "dirty"); the first message of a new session has no transcript file yet (gave `?`). Both fixed with tests.
- README: corrected wording on the token, CI status, the scope of placeholder checks; template no longer mentions the
  60-character rule.

Fixes from the first review (every case below has a regression test):

- Decisions: a message counts as recorded only when its **full** text is in `DECISIONS.md` (was: first 60 characters).
  Messages shorter than 20 characters must also carry their own UTC time in the same entry.
- Decisions: only known Claude Code wrappers are skipped (was: anything starting with `<`). Unreadable transcript lines
  give `?`, not `ok`. Results are `ok` / `nothing to check` / `FIX` / `?`.
- Readiness: template placeholders, a missing upstream (unless `--no-remote`) and unpushed commits give NOT READY.
  The snapshot lives in the untracked `.continuity/`, so READY leaves the tree clean.
- New `PreCompact` hook (`snapshot.py`) takes the snapshot before every compaction, manual or automatic.
- First prompt: a snapshot that no longer matches git head, `STATE.md` and `DECISIONS.md` is rebuilt from the current
  files with a warning, never presented as current.
- Acknowledgement is per session (see the second-review fix above for the token).
- Failures to write state are reported to the user and the model; the guard prints `?`, not `ok`.
- Malformed hook input, naive timestamps and undecodable files no longer crash a hook.
- Secret-like values in `docs/*.md` are flagged; the protocol says to record them as `[REDACTED]`.
- Large transcripts are entered by binary search on timestamps (408 MB transcript: 4.9 s -> 0.4 s per message).
- CI: GitHub Actions (Linux, Windows, macOS; Python 3.9 and 3.13) and GitLab CI.

## 0.1.0 (2026-10-26)

First version.
