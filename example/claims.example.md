# claims.example.md — declared success criteria

> This file is a working instance of the claim format, not documentation *about*
> the format. `scripts/claim_gate.py` parses the comments below and verifies
> each one against the filesystem.
>
> That makes it a live check, not a fixture. Edit `knowledge/style-rules.md`
> and drop a rule, and the count claim below stops holding. The gate fails, and
> the failure names the file. A fixture would have kept passing.

## Claims

<!-- The three source files the index is built from must exist. -->

- [x] the three knowledge sources exist
  <!-- claim-gate:exists:knowledge/style-rules.md -->
  <!-- claim-gate:exists:knowledge/constraints.md -->
  <!-- claim-gate:exists:knowledge/project-profile.md -->

- [x] `style-rules.md` still carries all eight rules
  <!-- claim-gate:count:knowledge/style-rules.md:WHEN:8 -->

- [x] `constraints.md` is a real document, not a stub
  <!-- claim-gate:lines:knowledge/constraints.md:15 -->

- [x] `project-profile.md` still documents the idempotency key
  <!-- claim-gate:contains:knowledge/project-profile.md:idempotency -->

- [x] the hand-maintained catalog and the navigation index are both present
  <!-- claim-gate:exists:data-catalog.example.json -->
  <!-- claim-gate:exists:MEMORY.example.md -->

## Reading a failure

```
  FAIL [count] TOO FEW: found 7x in example/knowledge/style-rules.md (min 8)
CLAIM:FAIL:1_of:7
```

The message names the file and the shortfall. There is no summary to interpret
and no log to correlate: the check and its evidence are the same line.

## The asymmetry that makes this useful

PASS means *not disproven*. A file that exists can still be wrong. But a file
that does not exist is definitely not done — so the gate is only ever certain
in the negative, which is the one direction where certainty is actually
available. Claiming more than that would make the gate another thing to
distrust.
