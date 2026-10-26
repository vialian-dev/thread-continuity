# thread-continuity

**Carry a Claude Code thread's working state across context compaction, and check that it was carried.**

When a Claude Code conversation fills its context window, it is compacted: the history is replaced by a summary.
A summary can lose the exact words of a decision, the reason an option was rejected, or which step comes next.
In a thread that runs for days this adds up: settled questions are asked again, finished work is redone, or an
old plan is continued as if it were current.

Claude Code provides the mechanics: auto-compaction, `/compact`, and hooks that run before compaction
(`PreCompact`) and after it (`SessionStart` with matcher `compact`). This package adds a protocol on top of them:
what the thread keeps in files, a snapshot taken before every compaction, a first prompt inserted after it, and
an advisory check on every user message.

> The conversation is temporary; the files are the memory.

## How it works

```text
during work     record decisions verbatim, progress, next step in docs/*.md; commit, push
before compact  snapshot.py (PreCompact hook, manual and auto) or relocate.py (by hand):
                checks the files and git, fingerprints STATE.md + DECISIONS.md + git head
after compact   first_prompt.py (SessionStart hook): inserts the first prompt into the same thread;
                if the files changed since the snapshot, rebuilds it from the current files and says so
first turn      the thread reads it and runs ack.py <token>; a fresh token per session and restore
every message   guard.py (UserPromptSubmit hook): one advisory line: ok / FIX / ?
```

## What is in the box

| File | Role |
| --- | --- |
| `tools/continuity/snapshot.py` | `PreCompact` hook. Runs the readiness and decisions checks, writes the snapshot to `.continuity/` with any problems found. Never blocks automatic compaction; can block a manual `/compact` when `CONTINUITY_BLOCK_MANUAL=1`. |
| `tools/continuity/relocate.py` | The same checks by hand, with a READY / NOT READY verdict and the list of what was checked. |
| `tools/continuity/first_prompt.py` | `SessionStart(compact)` hook. Inserts the first prompt; refuses to present a stale snapshot as current. |
| `tools/continuity/session_start.py` | `SessionStart(startup, clear)` hook. Registers that a session started fresh, so the guard never infers "new session" from a missing transcript. |
| `tools/continuity/ack.py` | `ack.py <token>`: the thread presents the token from its first prompt; changes exactly one session record. |
| `tools/continuity/guard.py` | `UserPromptSubmit` hook. Advisory line: first prompt acknowledged (A), user messages recorded (D), secret-like values in docs (S). |
| `templates/docs/*.md` | The files the thread keeps: `STATE.md` (goal and first action), `DECISIONS.md`, `PROGRESS.md`, `BACKLOG.md`, `LESSONS.md`. |
| `templates/CLAUDE.continuity.md` | The protocol as instructions for the assistant; append to your `CLAUDE.md`. |
| `.claude/settings.example.json` | Hook configuration. |

Python 3.9+, standard library only. The CI workflow is configured to run the tests on Linux, Windows and macOS with
Python 3.9 and 3.13.

## Installation

1. Copy `tools/continuity/` into your project.
2. Copy `templates/docs/*` into your project's `docs/` and fill in `docs/STATE.md`.
3. Merge `.claude/settings.example.json` into your project's `.claude/settings.json`. Where `python` is not
   Python 3, write `python3` in the commands.
4. Append `templates/CLAUDE.continuity.md` to your `CLAUDE.md`.
5. Add `.continuity/` to `.gitignore`. Commit and push.
6. Check: `python tools/continuity/relocate.py` should print `RESULT: ready for compaction`.

## What the output looks like

Ready:

```text
$ python tools/continuity/relocate.py
Checked: T S F G P; D not checked here (no --transcript)
Snapshot 3f9a1c2e written to .continuity/
RESULT: ready for compaction
```

Not ready:

```text
NOT READY. Fix, commit, push, run again:
  S  '## First action' still contains a template placeholder (<...> or YYYY-MM-DD)
  P  1 commit(s) not pushed
Checked: T S F G P
```

Guard line on a user message:

```text
CONTINUITY GUARD 2026-10-26 13:10Z: A ok | D FIX: 2 user message(s) not recorded verbatim in docs/DECISIONS.md
CONTINUITY GUARD 2026-10-26 13:12Z: A FIX FIRST: first prompt after compaction not acknowledged; ... | D ok (14 checked)
CONTINUITY GUARD 2026-10-26 13:15Z: A ? (no session id in hook input; 0 pending in project) | D ? (1 transcript line(s) unreadable)
```

`?` means "could not check", with the reason; `wait` means "a newly registered session, transcript expected".
Neither is ever folded into `ok`.

## Rules the checks use

- **Recorded verbatim**: the user's full message, whitespace-normalised, appears in `docs/DECISIONS.md`. Messages
  shorter than 20 characters ("yes") must also share an entry with their own UTC time `HH:MM`. Secret-like values
  are compared as `[REDACTED]`, so a properly redacted record still counts.
- **Window**: only the last 36 hours of the transcript are checked, so an old gap does not block every future turn.
  On a user message, messages younger than 180 seconds are reported as "record now", not as gaps, because the
  assistant has not yet had a turn to write them. Before compaction there is no grace period: every unrecorded
  message is a problem, recorded in the snapshot and shown in the first prompt.
- **Repeats**: the same text at different times counts as separate messages; each is checked.
- **Unreadable lines**: a broken, newline-terminated line gives `?`; only an unterminated last line (still being
  written) is ignored.
- **Skipped**: tool results, `isMeta` entries, the compaction summary, and Claude Code wrappers such as
  `<command-name>` or `<system-reminder>`. Any other text, including text that starts with `<`, is checked.
- **Ready**: the truth files exist and are not empty; the `Current goal` and `First action` sections of `STATE.md`
  contain no template placeholders (other files are not checked for placeholders); the first action starts with
  today's date; git is clean; the branch has an upstream and nothing is unpushed.
- **Fresh snapshot**: git head and the hashes of `STATE.md` and `DECISIONS.md` equal the ones recorded at snapshot
  time.

## Limitations

- The guard is **advisory**. It prints a line into the context; it does not block work. Acting on it is the
  assistant's job, which is why the protocol tells it to fix `FIX` and `?` first.
- Checks are structural. READY says the files are present, the key sections are filled in, and git is pushed; it cannot tell whether the goal
  or the next step is *right*. "Recorded verbatim" is a text-match heuristic, not proof that the meaning was kept.
- `ack.py` proves the **token was presented**, not that the prompt was read or understood. The token is printed
  in the first prompt and also stored in that session's record under `.continuity/sessions/`. Each session and
  each restore gets its own token, so one acknowledgement changes one record.
- The transcript can lag behind the conversation (Claude Code writes it asynchronously). A message typed
  just before compaction may not be in the file yet when the PreCompact check reads it, and then it is not
  counted. An unterminated last line is ignored for the same reason. A missing transcript is never reported as `ok`:
  it is `wait` during the first 10 minutes of a session registered by `session_start.py`, and `?` otherwise.
- Nothing in the protocol requires a human review. Automated: the checks, the snapshot, inserting the first prompt,
  the guard line. The assistant: keeping the files and acknowledging the prompt. The human: making the decisions
  and seeing the guard line. Whether the restored thread actually does the first action is not checked; in our
  live test the model acknowledged the prompt and then chose a different next step.
- The transcript format (`*.jsonl`, `compact_boundary` entries) is what Claude Code writes today; it is not a
  documented API and may change. The guard then reports `?` rather than `ok`.
- Secret detection catches common token formats (OpenAI/Anthropic-style `sk-`, GitHub, Slack, AWS keys, private
  key headers, JWTs), not every secret. Personal data is not detected. The protocol tells the assistant never to
  write secrets; this check is a backstop.
- One project directory per truth set. Several sessions in the same directory share `docs/`; their
  acknowledgements are separate, their decisions log is not.

## Results

We use this protocol daily on long-lived threads that coordinate multi-agent coding work. A controlled
comparison (the same task in two threads, with and without the protocol; control questions about decisions and
next steps after compaction; errors, tokens and time recorded) is planned. Until its numbers are published here,
this README makes no claim about how much the protocol helps.

## Running the tests

```text
python -m pip install -r requirements-dev.txt
python -m pytest -q tests
```

The tests run each script the way Claude Code does (JSON on stdin, `CLAUDE_PROJECT_DIR` set) against temporary git
repositories, including every failure case found in review.

## Who made this

The Vialian team: people and AI agents working together. Whichever member wrote a given line, the team stands
behind it, and a person is responsible for every agent's work. Issues and pull requests are welcome.

## Documentation used

- Claude Code hooks reference: <https://code.claude.com/docs/en/hooks> (`PreCompact` with matchers `manual` / `auto`
  and input `trigger`, `transcript_path`, `session_id`; `SessionStart` with `source: "compact"` and
  `hookSpecificOutput.additionalContext`; `UserPromptSubmit` stdout added to context; `systemMessage`)

## License

MIT, see `LICENSE`.
