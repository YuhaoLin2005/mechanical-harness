# Project Profile — Helios

> **Source file.** Hand-maintained. Never generated.
> `scripts/build_index.py` compresses this into the `p` section of
> `example/knowledge-index.json`.
>
> This file is the demo stand-in for "everything a session needs to know about
> the project it is working on". Replace it with your own; the shape is the
> only thing the scripts depend on.

## Facts

- **name**: Helios
- **kind**: small internal HTTP service
- **owner**: platform team (2 people)
- **stage**: beta
- **repo**: private — this harness repo is the public companion, not the service
- **runtime**: one container, one SQLite file, no queue

## Interfaces

- **api**: `/v1/events` (POST, JSON body, idempotency key required)
- **storage**: `events.db`, single writer
- **deploy**: CI-gated, blue/green, rollback is one command

## Capabilities

- **observability**: structured JSON logs + three dashboards (latency, error rate, queue depth)
- **testing**: unit tests plus one end-to-end path; the end-to-end path is the only gate that has ever caught a real regression
- **on-call**: nobody yet — this is why the constraints file is short and strict

## Known Sharp Edges

- The single writer means a long migration blocks every write. Migrations run
  outside the request path for this reason.
- The idempotency key is required but not yet validated against a TTL; a replay
  after 24h is currently accepted twice.
