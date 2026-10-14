# Glossary

One term, one definition, one place. Other documents link here instead of
re-explaining, so that when a definition changes it changes in one file.

Terms are grouped by the layer they belong to. Within a group they are
alphabetical.

---

## The contract

### 0/2 contract

The rule that every gate exits `0` or `2` and nothing else. `2` means blocked;
`0` means "passed, or had nothing to check". `1` is reserved because Python
exits `1` on an unhandled exception, and a crashed gate must not be
indistinguishable from a gate that did its job. See
[ARCHITECTURE.md §3](ARCHITECTURE.md#3-the-exit-code-contract).

### fail open

When a gate cannot see the thing it needs to judge, it exits `0` instead of
`2`. Applied to `evidence_gate`, which cannot evaluate a claim when the
transcript is unreadable. The alternative — blocking when blind — means the
gate blocks everything the moment the plumbing changes, and a gate that blocks
everything gets disabled. See [ARCHITECTURE.md §5](ARCHITECTURE.md#5-event--script-wiring).

### gate

A script that reads structured input, makes a comparison, and is allowed to
stop the thing it is watching by exiting `2`. The comparison is mechanical:
regex, file existence, mtime, set membership. A judgement that needs a model is
not a gate; it is a suggestion, and it does not belong in this layer.

### negative control

A known-bad input that a gate is required to reject. `corpus/should_fail.txt`
is the repository's negative control for `sanitize.py`. It exists because a
gate that has never gone red is not evidence of anything — the only way to
distinguish "nothing bad was found" from "nothing is being looked for" is to
feed it something bad on purpose and watch it fail.

### receipt

A record written when a mechanism fires, used by that mechanism or by a human
to tell "this already happened" from "this has not happened". Receipts are
append-only. See **state file** for the naming rule that keeps them honest.

### signal

A machine-readable line a script prints to announce a condition, in the form
`DOMAIN:STATUS:detail`. `FRESHNESS:STALE`, `CLAIM:FAIL`, `EVIDENCE-GATE:BLOCK`.
The vocabulary is fixed and greppable so that a condition can be found with a
substring search rather than by reading prose.

A signal is not the same as a gate. A gate decides; a signal reports. Some
signals are produced by gates that also exit `2`, and some are produced by
components that never block anything.

---

## Knowledge

### asset

A thing the project owns that has value and can be lost: a document, a
credential, a dataset, a contact, a piece of evidence. Assets are described in
`example/data-catalog.example.json` and loaded into the `assets` table.

Each asset carries a **dtype** (which is a closed set — see
`ARCHITECTURE.md §7`), a **risk** (what happens if it is lost), and a
**freshness** (how long the value stays true).

### freshness

How long a piece of knowledge stays correct without being re-checked. Not a
timestamp — a duration, or a band like `30d`. A fact whose freshness has
elapsed is not necessarily wrong; it is unverified, which is a different and
more useful statement.

### HOT / WARM / COLD

The three loading tiers, and the cost contract attached to each.

| Tier | Loaded | Typical contents |
|---|---|---|
| **HOT** | Every session, before anything else | The identity and constraint layer — small, and wrong to be without. |
| **WARM** | When a trigger word appears | The routing table and everything it points at. The bulk of the knowledge. |
| **COLD** | On request, or when a task reaches for it | Archive, history, raw evidence. |

The point of the separation is that only HOT is paid for unconditionally. A
WARM entry that is never triggered costs nothing, which is what makes it safe
to have many of them.

### provenance

Recorded origin: which file, which line, which source a statement came from.
In this repository provenance is stored, not inferred. `constraints.md` carries
`(source: ...)` on every line, and the index records the mtime of every file it
read. Provenance that has to be reconstructed is provenance that will be
reconstructed wrongly.

### route

A one-hop mapping from a trigger word to a file path. Routes are declared in a
WARM table and loaded into the `routes` table. A route exists so that the
session reaches the right file **without searching**: the lookup is a substring
match, not a decision.

**One hop, not two.** A route pointing at another table that must itself be
consulted has moved the search rather than removed it.

### route router

The component that reads a prompt, matches it against the routes, and injects
up to four file pointers. Capped at four because an injection is paid for on
every turn it fires; a miss prints nothing at all, which is the property that
makes the mechanism free when it is not needed.

### source vs derived

**Source** files are hand-maintained and cannot be reconstructed from anything
else. **Derived** files are produced from source files by a script and can
always be rebuilt. The distinction determines what is committed: derived files
are gitignored, because a committed derived file eventually disagrees with its
sources and the disagreement is invisible.

`example/knowledge/*.md` is source. `example/knowledge-index.json` is derived.

---

## Verification

### claim

A statement about the filesystem that can be checked: *this file exists*, *this
file has 15 lines*, *this string appears in it*. Claims are declared in the
document itself, in a comment, next to the thing they describe:

```
<!-- claim-gate:exists:setup.md -->
<!-- claim-gate:lines:15:setup.md -->
```

A claim that cannot be expressed as a comparison is not a claim this layer can
hold, and writing it as one would be worse than not writing it at all.

### CLAIM:PASS means not disproven

`claim_gate` verifies declared claims. Passing means every claim that was
declared survived checking. It does **not** mean the document is complete,
correct, or well-written — only that nothing it asserted about itself turned
out to be false.

The asymmetry is deliberate: a mechanical gate can falsify a specific
statement, and cannot confirm a general one.

### DIM-1

The **identifier** dimension of sanitization: real paths, emails, account names,
key-shaped strings, long digit runs. Concrete nouns that name a person,
machine, or credential.

DIM-1 findings are **waivable** — if the value is genuinely not sensitive (a
path in a public repository, an email that is already a published contact), it
can be released with an explicit waiver, and the waiver is recorded.

### DIM-2

The **semantic** dimension of sanitization: statements that reveal authorship,
attribution, or intent, independent of any identifier. Four classes:

- a sentence that credits the work to a party other than the person presenting
  it, or that describes having been asked to present it;
- a document that refers to its own writer in the third person while elsewhere
  writing in the first person;
- a statement of why the text was written, in terms of its audience;
- a claim of sole ownership.

The classes are described rather than quoted, and the concrete strings live
only in `corpus/should_fail.txt`. That is deliberate: a document that quotes a
trigger phrase contains the trigger phrase, and would have to be exempted from
the check it is documenting.

DIM-2 findings are **not waivable**. A DIM-2 hit can only be removed by
rewriting the content, because the problem is the statement, not the string —
no wording of a false attribution becomes acceptable when a reviewer signs off
on it.

**DIM-2 runs before DIM-1.** Releasing identifiers first would hide the
semantic statements behind a clean-looking file, and the semantic dimension is
the one that cannot be fixed later. See [ARCHITECTURE.md §1](ARCHITECTURE.md#1-the-four-layers).

### evidence

In this repository's sense: a source file that was actually read, in this
session, before a claim about it was written. `evidence_gate` blocks a write
that asserts something about a source the transcript shows was never opened.

### honesty signature

One of four shapes of unreliable reporting that a regex can find: praise with
no evidence near it, an omission (errors and a completion claim with nothing
connecting them), hedging inside the blast radius of a failure, and a long run
of claims with almost no citations. See `scripts/quality_gate.py`.

These are crude on purpose. A crude pattern that can be pointed at and argued
with is worth more than a nuanced one that cannot be explained.

---

## Publication

### export scan

Running `sanitize.py` against the output of `git archive` — the tree that would
actually be published — rather than against the working directory. The working
directory contains gitignored files, editor leftovers, and build artifacts that
are not going anywhere; scanning it produces findings that cannot be acted on
and, past a certain volume, trains the reader to ignore the output. See
`sanitize.py --export-scan`.

### waiver

An explicit, recorded decision to release a DIM-1 finding. Waivers are per-run
and require the value to be named. There is no waiver mechanism for DIM-2, and
adding one would be the failure this whole layer exists to prevent.
