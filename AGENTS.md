# AGENTS.md

Rules for an agent working in this repository. Ten of them. They are stated as
imperatives because that is what they are — each one is a decision that has
already been made, and re-deciding it per task is how the system erodes.

The rules assume you are a language model with tools. They are written to be
followed without judgement calls, because the judgement calls are exactly where
the failure modes live.

---

## 1. Exit codes are `0` and `2`. Never introduce a third.

A gate exits `0` (passed, or nothing to check) or `2` (blocked). `1` stays
reserved for an interpreter crash. If you add a gate, it obeys this. If you add
a status code, you have broken the contract that lets every caller be written
the same way.

See [ARCHITECTURE.md §3](ARCHITECTURE.md#3-the-exit-code-contract).

## 2. Before writing a gate, write its negative control.

A gate ships with an input that must make it fail. `corpus/should_fail.txt` is
the repository's example: `sanitize.py` is only trusted because that file makes
it go red on demand.

If you cannot construct an input that makes your new gate fail, you have not
built a gate. Stop and say so rather than shipping a component that has never
returned `2`.

## 3. A gate that cannot see must exit `0`.

Fail open. State the blind condition in a comment at the point where you detect
it, so the next reader knows the choice was made rather than overlooked.

A gate that blocks when it is blind blocks everything the moment the plumbing
changes — and the fix applied under time pressure is to disable it, which is
worse than never having written it.

## 4. Never let a detection record and a completion record share a name.

`observed at time T` and `done at time T` are different facts and live in
different files. If you need a new state file, name it after which of the two
it holds, and add it to the table in
[ARCHITECTURE.md §4](ARCHITECTURE.md#4-state-file-semantics).

This is the single highest-consequence naming rule in the repository. When the
two are confused, staleness looks handled while the thing is still stale, and
every downstream check agrees with the wrong answer.

## 5. Derived files are gitignored. Do not commit them.

If a file can be rebuilt by running a script, it does not go in the repository.
A committed derived file eventually disagrees with its sources, and the
disagreement is invisible because both copies look authoritative.

The test: delete it, run the build, and diff. If the content comes back, it was
derived.

## 6. Provenance is recorded, never reconstructed.

Every constraint carries `(source: ...)`. The index records the mtime of every
file it read. If you add a statement of fact, add where it came from in the
same edit. Provenance that has to be recovered later will be recovered wrongly.

## 7. A path is resolved through `_paths.py`. Never hard-coded.

Every script reads `config.example.json` through `_paths.load_config()`. A
machine-specific absolute path in a source file is a bug: it makes the
repository unrunnable on a fresh clone, which is the only way anyone will ever
check it.

## 8. Sanitization runs DIM-2 before DIM-1, and DIM-2 is not waivable.

Semantic self-admission first, identifiers second. DIM-1 can be released with a
recorded waiver; DIM-2 can only be fixed by rewriting the content.

If you find yourself wanting a DIM-2 waiver, the correct move is to rewrite the
sentence. Adding the waiver is the failure mode.

See [GLOSSARY.md](GLOSSARY.md#dim-2).

## 9. Scan the export tree, not the working tree.

`sanitize.py --export-scan` runs against `git archive` output — what would
actually be published. The working directory contains gitignored files and
scratch state that are not going anywhere; findings from it cannot be acted on,
and a report full of those trains its reader to ignore the report.

## 10. Report what happened, including when it is "not done".

If a test failed, say it failed and show the output. If a step was skipped, say
it was skipped. If you could only verify part of something, say which part.

The failure this rule prevents is not lying, which is rare. It is the omission
that reads as success: "the gate passes" said in a session that also contains a
traceback, with nothing connecting the two. `quality_gate` looks for exactly
that shape, and it will find it in your own output.

---

## Working in this repository

```
python scripts/selftest.py              # everything, including the red paths
python scripts/selftest.py --expect-fail # prove each gate can actually go red
```

Before claiming a change works, run the first. Before claiming a *gate* works,
run the second.

The two are different claims. The first says the system is consistent. The
second says the mechanisms that are supposed to fail when something is wrong
actually do. A repository can pass the first for a long time while failing the
second completely.
