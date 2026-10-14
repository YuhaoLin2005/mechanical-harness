# Constraints — Project Helios

> **Source file.** Hand-maintained. Never generated.
> `scripts/build_index.py` compresses this into the `c` section of
> `example/knowledge-index.json`.
>
> `[HARD]` = violated means the change is rejected. `[SOFT]` = violated means
> someone has to say why out loud. The tier is part of the entry, not a comment
> about it, because the gate reads the tier and nothing else.

## Hard

- [HARD] A document must not state a number that no command in the repo can reproduce. (source: incident-2026-03, a metric copied from a chat message)
- [HARD] No gate may exit 0 when it found something. A green light that cannot turn red is worse than no light. (source: incident-2026-01, a check that never fired)
- [HARD] Source files are edited by hand; derived files are rebuilt. A derived file is never hand-edited. (source: design-review-2026-02)

## Soft

- [SOFT] One commit per logical change; a commit that needs "and" to describe it is two commits. (source: team-convention)
- [SOFT] Prefer deleting a mechanism to configuring it. (source: retrospective-2026-04)
- [SOFT] A state file's name states its semantics; two files that record different events never share a name. (source: incident-2026-05, a detection record read as a completion record)
