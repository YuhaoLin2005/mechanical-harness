# mechanical-harness

**A small set of mechanical gates for an agent that works on files.**

Not a framework. Ten scripts, no dependencies, no service to run. Each one
answers a question a language model is bad at answering about itself, and
answers it with a comparison instead of an opinion.

---

## The problem

An agent that writes files has four failure modes that no amount of good
instruction removes, because in each case the thing that would notice is the
same thing that is failing:

| Failure | Why prompting does not fix it |
|---|---|
| It writes a claim about a file it never opened | The output is fluent either way. Fluency is not evidence. |
| It reports a derived file as current after the source changed | Nothing about the derived file records when it was made. |
| It says "done" while the artifacts disagree | "Done" is cheap to type and expensive to be wrong about. |
| It commits a credential or runs something irreversible | By the time anyone notices, there is no undo. |

Each of these has a mechanical tell. That is the whole idea: **if a failure has
a tell, a comparison can find it, and a comparison does not get tired or
optimistic.**

---

## How it fits together

```
  user prompt
      │
      ▼
 ┌──────────────────┐  UserPromptSubmit
 │  route_router    │ ───────────────► injects up to 4 file pointers, or nothing
 └──────────────────┘                  (a miss costs zero tokens)
      │
      ▼
 ┌──────────────────┐  PreToolUse
 │ sensitive_path   │  blocks writes to secrets and commands with no inverse   exit 2
 │ _guard           │
 ├──────────────────┤
 │  evidence_gate   │  blocks a claim whose source was never read this session exit 2
 └──────────────────┘
      │
      ▼  the write lands
 ┌──────────────────┐  SessionStart, and after any edit
 │  build_index     │ ──► records the mtime of every source it read, inside the index
 │  freshness_check │ ◄── compares those mtimes against the live files            exit 2
 └──────────────────┘
      │
      ▼
 ┌──────────────────┐  Stop
 │  quality_gate    │  four known dishonesty signatures in the turn              exit 2
 │  claim_gate      │  declared success criteria, checked against the filesystem  exit 2
 └──────────────────┘
```

Two components feed the ones above them and are worth naming: `build_assets_db`
turns the navigation index into a queryable inventory, and `sanitize.py` is the
gate that keeps all of this publishable.

---

## Quickstart

```
git clone <this repo>
cd mechanical-harness
python scripts/selftest.py
```

One command, no configuration, no network. It builds the index, runs the demo
queries, exercises every gate — and then deliberately corrupts things to prove
each gate can actually fail. Exit 0 means the whole thing works, including its
red paths.

---

## Files

| Path | What it is |
|---|---|
| `README.md` | This file. |
| `ARCHITECTURE.md` | The one deep document: layers, data flow, the exit-code contract, state-file semantics, the SQL schema, how to add a gate. |
| `GLOSSARY.md` | Every term defined once. Other documents link here rather than re-explaining. |
| `AGENTS.md` | Ten numbered rules for an agent working in this repository. |
| `INSTALL.md` | A script to paste into an agent session to wire this into an existing project. |
| `config.example.json` | Path resolution. Every script reads it; nothing is hard-coded. |
| `hooks/claude-code.json` | The `hooks` block for Claude Code, resolved through `$CLAUDE_PROJECT_DIR`. |
| `scripts/selftest.py` | Runs everything above, including the deliberate failures. |
| `scripts/build_index.py` | Compresses the knowledge sources into one small JSON index, recording each source's mtime. |
| `scripts/freshness_check.py` | The source-to-derived staleness gate. |
| `scripts/build_assets_db.py` | The asset inventory as SQLite, with a CHECK constraint that rejects unknown categories. |
| `scripts/route_router.py` | Trigger-word routing, capped at four pointers, silent on a miss. |
| `scripts/claim_gate.py` | Declared success criteria, verified against the filesystem. |
| `scripts/evidence_gate.py` | Blocks a claim about a source that was not read. |
| `scripts/sensitive_path_guard.py` | Blocks secret paths and irreversible commands. |
| `scripts/quality_gate.py` | Four honesty signatures, run at the end of a turn. |
| `scripts/sanitize.py` | The publication gate: semantic self-admission first, then identifiers. |
| `scripts/_paths.py` | Shared configuration resolution. Not an entry point. |
| `example/` | A complete, runnable demo deployment. Replace it with your own. |
| `corpus/should_fail.txt` | The negative control. `sanitize.py` is only trusted because this file makes it fail on demand. |

---

## The four layers

Every component belongs to exactly one. The layering is the reason the pieces
compose.

| Layer | Question it answers | Components |
|---|---|---|
| **Configuration** | Where is everything, and what is wired to what? | `config.example.json`, `hooks/claude-code.json`, `_paths.py` |
| **Knowledge** | What does the project know, and is it still true? | `build_index`, `freshness_check`, `build_assets_db`, `route_router` |
| **Verification** | Is this claim allowed to be written? | `claim_gate`, `evidence_gate`, `sensitive_path_guard`, `quality_gate` |
| **Publication** | What may leave? | `sanitize.py`, `corpus/` |

Details in [ARCHITECTURE.md](ARCHITECTURE.md#1-the-four-layers).

---

## Where do I look for…

| I want to… | Go to |
|---|---|
| change what triggers a route | `example/MEMORY.example.md` (the WARM table) |
| add a fact about the project | `example/knowledge/project-profile.md` |
| add a rule, and record why it exists | `example/knowledge/constraints.md` |
| see a gate fail on purpose | `python scripts/selftest.py --expect-fail` |
| understand why a gate blocked | `.state/gates.jsonl` — every firing records the trigger that fired it |
| add a new gate | [ARCHITECTURE.md §8](ARCHITECTURE.md#8-adding-a-gate) |
| change where files live | `config.example.json` — nothing else hard-codes a path |
| publish this repository somewhere | `python scripts/sanitize.py --export-scan` |

---

## Scope — what is deliberately not here

This repository is a **curated extract**, not a distribution.

The system it was drawn from has more components than these ten: scheduling and
cost accounting, transcript analysis, and a number of gates that encode
decisions specific to one machine and one workflow. They are absent. Absent is
not the same as withheld — a component you cannot run is documentation, and
documentation is not what this repository is for.

Two consequences worth stating plainly:

- **This is not evidence of scale.** Ten scripts that run is a different claim
  from eighty-nine that existed. Only the first one is being made here.
- **The numbers in this repository are demo numbers.** The asset counts, the
  route counts, and the token figures come from `example/`, which is synthetic.
  Nothing here should be read as a benchmark.

---

## Requirements

- Python 3.8 or newer. Standard library only.
- Optional: `PyYAML`, to use the YAML frontmatter form of `claim_gate`'s
  declarations. The HTML-comment form, which the example uses, needs nothing.

Tested on Windows and Linux. Paths are resolved relative to the repository root,
so no file contains a machine-specific absolute path.

---

## License

MIT. See [LICENSE](LICENSE).
