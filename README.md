# thread-continuity

**Keep a long Claude Code thread smart across context compaction.**

When a Claude Code conversation fills its context window, it is compacted: the history is replaced by a summary.
Summaries lose things: the exact words of a decision, why an option was rejected, which step comes next.
In a thread that runs for days, that loss adds up. The assistant re-asks settled questions, redoes finished
work, or confidently continues from a stale plan.

This package is a small protocol plus four scripts that make compaction a planned move instead of an accident.
Claude Code already provides the building blocks: auto-compaction, `/compact`, and hooks that fire after
compaction (`SessionStart` with matcher `compact`). What it leaves to you is *what* the thread must keep and
*how* to prove it kept it. That part is here.

## The idea in one paragraph

The conversation is temporary; the files are the memory. Everything the thread knows that matters
(the user's decisions verbatim, the current goal, the next step, progress, lessons) is written to a few
Markdown files in git **as it happens**. Before compaction, a script checks that nothing lives only in the
conversation. After compaction, a hook puts a "first prompt" into the same thread: what to read and what to do
first. The thread confirms it read it, and a guard keeps saying "fix this first" until it does.

```text
 work ──► record in docs/*.md, commit, push ──► relocate.py: READY? ──► /compact
                                                     │ no: lists what to fix
                                                     ▼
   guard.py nags until ack ◄── thread reads, runs ack.py ◄── first_prompt.py hook inserts FIRST_PROMPT.md
```

## What is in the box

| File | Role |
|---|---|
| `tools/continuity/relocate.py` | Readiness check before compaction. Passes only when every truth file exists, today's first action is written down, and git is clean and pushed. Then writes `FIRST_PROMPT.md`. |
| `tools/continuity/first_prompt.py` | `SessionStart(compact)` hook. Inserts `FIRST_PROMPT.md` into the same thread right after compaction and raises a "not yet read" flag. |
| `tools/continuity/ack.py` | The thread runs it after reading the first prompt; clears the flag. |
| `tools/continuity/guard.py` | `UserPromptSubmit` hook. One line on every user message: was the first prompt acknowledged, and is every user message recorded verbatim in `docs/DECISIONS.md`? |
| `templates/docs/*.md` | The truth set: `STATE.md` (goal + first action), `DECISIONS.md`, `PROGRESS.md`, `BACKLOG.md`, `LESSONS.md`. |
| `templates/CLAUDE.continuity.md` | The protocol as instructions for the assistant; paste into your `CLAUDE.md`. |
| `.claude/settings.example.json` | Hook configuration. |

Python 3.9+, standard library only. Works wherever Claude Code hooks run: the terminal CLI and the
VS Code extension both read `.claude/settings.json`.

## Install (5 minutes)

1. Copy `tools/continuity/` into your project.
2. Copy `templates/docs/*` into your project's `docs/` and fill in `STATE.md`.
3. Merge `.claude/settings.example.json` into your project's `.claude/settings.json`
   (on systems where `python` is Python 2 or missing, use `python3`).
4. Append `templates/CLAUDE.continuity.md` to your `CLAUDE.md`.
5. Add `.continuity/` to `.gitignore`.
6. Commit. From now on, before compacting: `python tools/continuity/relocate.py`.

## Why verbatim decisions

A summary of "the user agreed to X" is a paraphrase written by the same model that may have misunderstood
X. The user's exact words, with a timestamp, are the only record that cannot drift. The guard checks the first
60 characters of each user message against `DECISIONS.md`, so a skipped or paraphrased decision shows up on
the very next turn, not three compactions later.

## Why a guard and not just instructions

Instructions in `CLAUDE.md` depend on the model's attention, and attention is exactly what degrades in a long
thread. A hook runs every time, prints one line into the context, and prints `?` when it cannot measure
something, never a false `ok`. Rules that matter should be enforced by tools; the model's job is to act on
what they report.

## Results

We run this protocol daily on long-lived threads that coordinate multi-agent coding work. A controlled
measurement (the same task in two threads, with and without the protocol, ten control questions about
decisions and next steps after compaction) is in progress; numbers will be published here when they exist.
Until then this README makes no claim about how much it helps.

## Who made this

The Vialian team: people and AI agents working together. Whichever member wrote a given line, the team stands
behind it, and a person is responsible for every agent's work.

Issues are welcome. Our agent reads them first and answers when it can; people step in when it cannot.

## Documentation used

- Claude Code hooks: https://code.claude.com/docs/en/hooks (events `SessionStart` with matcher `compact`,
  `UserPromptSubmit`; JSON output `hookSpecificOutput.additionalContext`, `systemMessage`)

## License

MIT, see `LICENSE`.
