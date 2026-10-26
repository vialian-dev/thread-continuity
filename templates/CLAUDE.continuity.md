## Thread continuity protocol (append to your CLAUDE.md)

The conversation is temporary; the files are the memory. Compaction can happen at any moment, so:

1. **Record as you go, in git.** Every user message goes verbatim into `docs/DECISIONS.md` with its UTC time and
   what follows from it. Work done goes into `docs/PROGRESS.md`, plans into `docs/BACKLOG.md`, lessons into
   `docs/LESSONS.md`. Commit and push within the hour.
2. **Never record secrets.** Passwords, API keys, tokens and private keys are written as `[REDACTED]`, even when
   the user pasted them. If the guard prints `S WARN`, redact the value, rewrite the commit if it was pushed, and
   tell the user to rotate the secret.
3. **Keep the first action current.** `docs/STATE.md` always names the current goal and, under `## First action`,
   today's date and the single next step.
4. **Before a manual compaction** run `python tools/continuity/relocate.py` until it prints
   `RESULT: ready for compaction`. Automatic compaction is covered by the PreCompact hook, which takes the snapshot
   itself and carries any problems into the first prompt.
5. **After compaction** the first prompt is inserted into the same thread. Read it and the files it names, then run
   `python tools/continuity/ack.py <snapshot id>` with the id printed in the prompt. Start from the first action.
   Do not retell or search the old conversation.
6. **When the guard line says FIX or ?**, deal with it before other work.
7. **Time comes from the clock** (`date -u`), never from memory.
