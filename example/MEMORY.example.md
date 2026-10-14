# MEMORY.example.md — the navigation index

> This file is the demo stand-in for "the index a session loads at startup".
> It is also a **routing table**: the WARM section below is parsed by
> `scripts/build_assets_db.py` into the `routes` table and by
> `scripts/route_router.py` at request time.
>
> That is deliberate. The repo's own navigation is the router's first input —
> the component is not described in prose anywhere, it is exercised on the
> document you are reading.
>
> Tier vocabulary is defined once, in GLOSSARY.md.

> 🔥 HOT = loaded every session · 🟡 WARM = loaded on a trigger word · ❄️ COLD = archived, fetched on demand

## 🔥 HOT — loaded every session

- [Project Profile](knowledge/project-profile.md) — what Helios is, who owns it, what breaks
- [Constraints](knowledge/constraints.md) — the rules that reject a change

## 🟡 WARM — trigger-word loaded

> One hop: the first action is a concrete file path. No second-guessing.

| trigger keywords | first action (file path) |
|---|---|
| deploy / release / ship / rollback / blue-green | knowledge/constraints.md |
| style / wording / tone / phrasing / how to write | knowledge/style-rules.md |
| incident / outage / postmortem / on-call / regression | knowledge/constraints.md |
| owner / team / stage / project facts / what is helios | knowledge/project-profile.md |
| api / endpoint / schema / events / idempotency | knowledge/project-profile.md |
| test / coverage / unit / end-to-end / flaky | knowledge/project-profile.md |
| constraint / hard rule / soft rule / policy | knowledge/constraints.md |
| sharp edge / known issue / limitation / caveat | knowledge/project-profile.md |

## ❄️ COLD

Not part of this example. In a real deployment this section points at an archive
directory of dated notes; the router never reads it, and no gate counts it.
