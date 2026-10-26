## Thread continuity protocol (paste into your CLAUDE.md)

The conversation is temporary; the files are the memory. Compaction can happen at any moment, so:

1. **Record as you go, in git.** Every user message goes verbatim into `docs/DECISIONS.md` with UTC time and its
   consequence. Work done goes into `docs/PROGRESS.md`, plans into `docs/BACKLOG.md`, lessons into `docs/LESSONS.md`.
   Commit and push within the hour.
2. **Keep the first action current.** `docs/STATE.md` always names the current goal and, under `## First action`,
   today's date and the single next step.
3. **Before compaction** run `python tools/continuity/relocate.py` until it prints `RESULT: ready for compaction`,
   commit `FIRST_PROMPT.md`, then compact.
4. **After compaction** the hook inserts `FIRST_PROMPT.md` into the same thread. Read it and the files it names, run
   `python tools/continuity/ack.py`, then start from the first action. Do not retell or search the old conversation.
5. **When the guard line says FIX**, fix it before any other work.
6. **Time comes from the clock** (`date -u`), never from memory.
