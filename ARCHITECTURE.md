# Architecture

The one deep document. Everything else in this repository is either a
definition ([GLOSSARY.md](GLOSSARY.md)), an instruction ([AGENTS.md](AGENTS.md)),
or an instance (`example/`).

---

## 1. The four layers

Each component belongs to exactly one layer, and the layering is what lets the
pieces compose without knowing about each other.

| Layer | Question | Components | Depends on |
|---|---|---|---|
| **Configuration** | Where is everything? | `config.example.json`, `hooks/claude-code.json`, `_paths.py` | nothing |
| **Knowledge** | What does the project know, and is it still true? | `build_index`, `freshness_check`, `build_assets_db`, `route_router` | Configuration |
| **Verification** | Is this claim allowed to be written? | `claim_gate`, `evidence_gate`, `sensitive_path_guard`, `quality_gate` | Knowledge |
| **Publication** | What may leave? | `sanitize.py` | everything above |

Dependencies point one way only. No verification gate reads the configuration
directly; it goes through `_paths.py`. No gate reads the knowledge files; it
reads the knowledge *index*, or the asset database, which are the stable
shapes. The reason is not purity — it is that the path a component uses to
reach data is the path that has to change when the data moves, and one place to
change beats ten.

---

## 2. Data flow, end to end

```
                       config.example.json
                              │
                    ┌─────────┴─────────┐
                    ▼                   ▼
          example/knowledge/*.md   example/MEMORY.example.md
           (hand-maintained)        (hand-maintained)
                    │                   │
        build_index │                   │ build_assets_db
                    ▼                   ▼
      example/knowledge-index.json   example/data-assets.db
       ┌────────────┴──────────┐       ┌──┴───────────────┐
       │  _meta.sm: {file:mtime}│       │ routes  (derived)│
       │  sr / c / p            │       │ assets  (source) │
       └────────────┬──────────┘       └──┬───────────────┘
                    │                     │
        freshness_check                   │ route_router
        (compare mtime, exit 2)           │ (match, cap 4, silent miss)
                    │                     │
                    └──────────┬──────────┘
                               ▼
                    what the session sees

  ── and independently ──────────────────────────────────────────

   a write  ──►  sensitive_path_guard ──►  evidence_gate  ──►  lands
                       │                        │
                     exit 2                   exit 2

   turn end ──►  quality_gate  ──►  claim_gate  ──►  transcript,
                     │                  │             .state/honesty-flags.jsonl
                   exit 2             exit 2         .state/gates.jsonl
```

The two halves meet at exactly one place: the verification gates read the
knowledge files as their *evidence* (`evidence_gate` requires that a source was
read; `claim_gate` requires that a target exists). They never read the index.
That is intentional — a gate that consulted a derived file could be satisfied
by a stale derived file.

---

## 3. The exit-code contract

**Every gate exits 0 or 2. Nothing else.**

| Code | Meaning |
|---|---|
| `0` | Passed, or had nothing to check. These are the same outcome and are deliberately not distinguished. |
| `2` | Blocked. Something was found and the caller must deal with it. |

Why only two codes, and why `2` rather than `1`:

- **`1` is unavailable.** Python exits `1` on an unhandled exception. If `1`
  also meant "gate failed", a crashed gate and a failing gate would be
  indistinguishable, and a crashed gate is the more dangerous of the two
  because it is silent and looks like a pass in any script that checks
  `if $? -gt 0`. Using `2` keeps the two apart.
- **Silence is not success.** A gate with nothing to check exits `0` and prints
  nothing. It does not print "OK". Output is reserved for things the caller
  needs to act on.
- **Every gate must be able to produce `2`.** A gate that has never returned
  `2` is not a gate; it is a line of logging. `scripts/selftest.py --expect-fail`
  exists to enforce this and is the reason the repo ships `corpus/should_fail.txt`.

**Non-blocking hooks append `|| exit 0`.** `route_router` and the Stop-time
`claim_gate` in `hooks/claude-code.json` are wrapped this way. It is not a
workaround; it is the statement that those components are not allowed to stop
anything.

---

## 4. State-file semantics

State files are the API between a mechanism and whoever consumes it. The names
are the contract, and the contract has one rule:

> **A file that records that something was observed and a file that records
> that something was done are different files, and they never share a name.**

Mixing them is the specific failure this rule prevents. When a detection record
is read as a completion record, staleness looks handled while the thing is
still stale, and every downstream check agrees with the wrong answer.

| File | Written by | Means | Does **not** mean |
|---|---|---|---|
| `.state/freshness-stale.json` | `freshness_check.py` | "staleness was **observed** at this time, for these sources" | that a rebuild happened |
| `.state/last-index-build.json` | `build_index.py` | "a build **completed** at this time" | that anything is currently fresh |
| `.state/gates.jsonl` | every gate, append-only | every firing, with the trigger that fired | that the block was correct |
| `.state/honesty-flags.jsonl` | `quality_gate.py`, append-only | honesty signatures seen in a turn | that the turn was dishonest |
| `.state/guard-blocks.jsonl` | `sensitive_path_guard.py`, append-only | every block, with rule and match | that the block was a true positive |

All of them are gitignored. They describe one session's history, not the
project; a repository that commits them accumulates a record of arguments with
itself.

`gates.jsonl` exists for a specific reason worth keeping: a gate log that
records only *that* a gate fired, and not **which pattern fired**, cannot be
tuned. The alternatives are to guess, or to loosen the pattern until it stops
complaining — and loosening until silence is how a gate dies.

---

## 5. Event → script wiring

| Event | Script | Blocking? | On `2` |
|---|---|---|---|
| `SessionStart` | `freshness_check.py` | no | Staleness is surfaced; the session proceeds. A stale index is a warning, not a stop. |
| `UserPromptSubmit` | `route_router.py` | no | Never exits 2. Wrapped `|| exit 0`. A router with no match prints nothing. |
| `PreToolUse` (`Write\|Edit\|Bash`) | `sensitive_path_guard.py` | **yes** | The tool call does not happen. The block is recorded. |
| `PreToolUse` (`Write\|Edit`) | `evidence_gate.py` | **yes** | The write does not land. The message names the file to read. |
| `Stop` | `quality_gate.py` | **yes** | The turn is flagged. |
| `Stop` | `claim_gate.py` | **yes** | Failed declarations are listed. |

Order within `PreToolUse` matters: the path guard runs first because "this is a
credential file" is a cheaper and more certain judgement than "this claim needs
evidence", and a call that is going to be blocked for the first reason should
not spend time on the second.

Wiring lives in `hooks/claude-code.json`. Every command is resolved through
`$CLAUDE_PROJECT_DIR` and every guard degrades to a no-op rather than a crash
when it cannot see: `evidence_gate` returns `0` when the transcript is
unavailable. **A gate that blocks when it is blind is a gate that blocks
everything the moment the plumbing changes.**

---

## 6. The freshness loop

The mechanism, in four steps:

1. `build_index.py` reads each source file and writes its **mtime** into the
   index it produces, under `_meta.sm`, alongside the relative path it will be
   re-checked at in `_meta._paths`.
2. `freshness_check.py` reads those recorded mtimes, stats the live files, and
   compares.
3. Any source more than `--min-delta` seconds newer than the index means the
   index is stale. It prints `FRESHNESS:STALE`, writes the detection record,
   and exits `2`.
4. The remedy is `build_index.py --build`, which rewrites the index — and with
   it the recorded mtimes.

Why the mtime is recorded *inside the derived file* rather than in a sidecar
manifest: the derived file and its provenance cannot then drift apart. There is
no arrangement of files in which the index was rebuilt and the mtimes were not,
or the mtimes were updated and the index was not, because they are the same
write.

The `--min-delta` guard (default 60s) exists because a rebuild reads its sources
and writes its output within the same filesystem timestamp tick. Without a
tolerance, a correct build reports itself stale.

**Deleting a source counts as staleness.** A source that cannot be found looks
exactly like a source that is fresh if the check only compares mtimes, so a
missing file is reported as `MISSING` and is not silently skipped.

---

## 7. The SQL asset layer

```sql
CREATE TABLE routes(
    id INTEGER PRIMARY KEY,
    kw TEXT,          -- comma-separated trigger words
    load_path TEXT,   -- the one-hop destination
    tier TEXT,        -- HOT / WARM / COLD
    verified INTEGER DEFAULT 0
);

CREATE TABLE assets(
    id INTEGER PRIMARY KEY,
    dtype TEXT,
    name TEXT,
    path TEXT,
    value TEXT,
    risk TEXT,
    context TEXT,
    freshness TEXT,
    verified INTEGER DEFAULT 0,
    tags TEXT,
    CHECK(dtype IN ('identity','capability','evidence','work','knowledge',
                    'relationship','feedback','creation','raw','config','metadata'))
);
```

The `CHECK` constraint is doing real work. `dtype` is a closed set: an asset
whose type is misspelled fails the build, rather than creating a category of one
that no query will ever match. A taxonomy without a constraint degrades into
free text, and free text is not queryable.

Three queries worth having on hand:

```sql
-- What is at risk of going stale?
SELECT dtype, name, freshness FROM assets WHERE freshness IN ('30d','stale');

-- What would be unrecoverable to lose? (drives backup priority)
SELECT dtype, name FROM assets WHERE risk LIKE '%not recoverable%';

-- Which routes exist for a topic?
SELECT kw, load_path FROM routes WHERE kw LIKE '%rollback%';
```

The same queries run as `python scripts/build_assets_db.py --demo`.

**The two tables hold different kinds of truth.** `routes` is derived — delete
the database and it comes back from the markdown. `assets` is source — the
catalog behind it is hand-maintained and not derivable from anything. That
asymmetry is why the database is gitignored: it is regenerable, and committing a
regenerable file means the committed copy eventually lies.

---

## 8. Adding a gate

The shape every gate in this repository follows:

1. **Read the payload from stdin as JSON.** Never from arguments — hooks get
   their input on stdin, and a gate that only works from the command line is a
   gate that does not run in the place it matters.
2. **Decide, using only comparisons.** Regex, mtime, existence, membership. If
   the decision needs a model, it is not a mechanical gate and does not belong
   in this layer.
3. **Print a machine-readable line** of the form `DOMAIN:STATUS:detail...`.
   `EVIDENCE-GATE:BLOCK`, `QUALITY:BLOCK`, `GUARD:BLOCK`, `FRESHNESS:STALE`,
   `CLAIM:FAIL`. The vocabulary is greppable on purpose.
4. **Exit `0` or `2`.** Nothing else. See section 3.
5. **Fail open.** If the gate cannot see what it needs, exit `0`. State the
   blind condition in a comment so the next reader knows it was chosen.
6. **Record the firing**, including *which pattern fired*.
7. **Ship a self-test that proves the gate can go red**, and make the corpus
   real. A self-test written from the same imagination that wrote the pattern
   tests the pattern against itself.

Then wire it into `hooks/claude-code.json`, add it to the table in
[README.md](README.md), and add a `--selftest` line to `scripts/selftest.py`.

The last step is the one that gets skipped. A gate that is not in `selftest.py`
is a gate nobody knows is broken until it matters.
