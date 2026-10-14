# Style Rules — Project Helios

> **Source file.** Hand-maintained. Never generated.
> `scripts/build_index.py` compresses this into the `sr` section of
> `example/knowledge-index.json`. Edit here, then rebuild the index.

Each rule is one line with three slots, separated by `→`:

```
- WHEN <condition> → USE <what to do> → AVOID <the anti-pattern>
```

The point of the three slots is that a rule with no `AVOID` slot is not a rule —
it is a preference. A rule that cannot name the failure it prevents has never
been tested.

## Rules

- WHEN answering a direct question → USE the shortest complete answer, starting with the answer → AVOID a preamble that restates the question
- WHEN explaining a design decision → USE context → decision → consequence, in that order → AVOID a flat list of facts with no causal link
- WHEN a task touches more than three files → USE a written plan first → AVOID starting the edit and discovering the shape halfway through
- WHEN reporting a result → USE the command that produced it and its exit code → AVOID the adjective without the evidence
- WHEN something failed → USE the failure verbatim, first sentence → AVOID burying it under what did work
- WHEN a number appears in a document → USE the file it came from → AVOID a number that cannot be traced to a command
- WHEN writing a comment → USE why the code is this way → AVOID what the code plainly does
- WHEN a rule is added → USE the incident that motivated it → AVOID a rule with no recorded failure behind it
