# INSTALL.md

How to put this in an existing project.

There are two ways, and they are for different situations.

- **By hand** — three steps, five minutes, and you will understand what you
  installed. Do this if you are setting this up for yourself.
- **By agent** — paste one block into an agent session and let it do the work.
  Do this if you want it in a project you are not going to read closely.

Both end in the same place. Neither is reversible-free: read
[What this does not do](#what-this-does-not-do) before either.

---

## By hand

### 1. Copy the parts you want

```
cp -r mechanical-harness/scripts      your-project/
cp -r mechanical-harness/example      your-project/
cp    mechanical-harness/config.example.json your-project/
```

`example/` is a working demo deployment. Keep it until you have replaced it,
because the scripts need something to read and an empty `knowledge/` directory
produces an empty index, which looks like a broken install.

### 2. Point the config at your files

Edit `config.example.json` — or copy it to `config.json`, which is gitignored
and takes precedence. Every path in it is relative to the project root.

The three you will actually change:

| Key | Set it to |
|---|---|
| `knowledge.dir` | the directory holding the notes this project runs on |
| `assets.routes_source` | the navigation index whose trigger table should become routes |
| `assets.catalog` | your asset inventory, or keep the example to start |

Nothing else needs to change. If a path in your project is absolute, that is
the thing to fix — see [AGENTS.md rule 7](AGENTS.md#7-a-path-is-resolved-through-_pathspy-never-hard-coded).

### 3. Build once, then wire

```
python scripts/build_index.py --build
python scripts/build_assets_db.py
python scripts/selftest.py
```

`selftest.py` exits `0` only if every component works **and** every gate can be
made to fail. If it exits `2`, the message names the component; do not wire the
hooks until it passes.

Then merge the `hooks` block from `hooks/claude-code.json` into your agent's
settings. It uses `$CLAUDE_PROJECT_DIR`, so there is nothing to edit — but merge
it into whatever is already in that file rather than replacing it, since
settings files usually carry other configuration.

---

## By agent

Paste the block below into an agent session started in the target project. It
is written to be self-contained: it says what to do, what not to do, and what
to report back.

> Copy everything between the rules, not the rules themselves.

---

You are installing `mechanical-harness` into this project. Work through the
steps in order and stop at the first one that does not behave as described.

**Constraints — these are not negotiable:**

- Do not modify, move, or delete any existing file in this project. You are
  adding files and merging one settings block. If a step seems to require
  changing something that already exists, stop and report it instead.
- Do not create a git commit, and do not run `git push`. The user reviews the
  diff before anything is committed.
- If a command exits `1`, that is a crash, not a gate result. Report the
  traceback and stop; do not work around it.
- Report what you actually saw. If a step failed, say it failed and include the
  output. Do not summarize a failure as a success.

**Steps:**

1. Copy `scripts/`, `example/`, and `config.example.json` into the project root.
   If any of those paths already exist, stop and report the collision.

2. Run `python scripts/selftest.py`. Report the exact output.
   - Exit `0` — continue.
   - Exit `2` — report the failing component and stop.
   - Exit `1` — report the traceback and stop.

3. Run `python scripts/selftest.py --expect-fail`. This checks that each gate
   actually fails when fed bad input. Report the exact output. It should exit
   `0`; anything else means a gate is not doing its job — report and stop.

4. Ask the user which directory holds their working notes, and which file is
   their navigation index. Do not guess from the file listing — a wrong guess
   here silently produces an empty index and the install looks successful.

5. Set `knowledge.dir` and `assets.routes_source` in `config.example.json` to
   those two paths. If the user has no existing notes, keep `example/` for now
   and say so in your report.

6. Run `python scripts/build_index.py --build` and then
   `python scripts/build_assets_db.py`. Report both outputs. The first should
   print `INDEX:OK` with a source count matching the number of files in the
   knowledge directory.

7. Merge the `hooks` block from `hooks/claude-code.json` into the project's
   agent settings, preserving everything already in that file. If the settings
   path is not obvious, ask rather than creating a new settings file.

8. Report back, in this order:
   - Which files you added (paths only, no descriptions).
   - The output of steps 2, 3, 6 verbatim.
   - Anything you could not determine and had to ask about.
   - What you did **not** verify.

Step 8's last item is the one that matters. An install report that omits what
was untested reads as a complete install, and the next person finds out which
parts were actually checked only when something breaks.

---

## What this does not do

- **It does not sandbox anything.** `sensitive_path_guard` blocks a list of
  patterns. It is a speed bump against a specific class of mistake, not a
  security boundary, and it will not stop an agent that is trying to do the
  wrong thing.
- **It does not make the agent honest.** `quality_gate` finds four shapes of
  unreliable reporting. There are more than four.
- **It does not delete anything**, including when it blocks. A blocked write
  simply does not happen; nothing already on disk is touched.
- **It does not check your knowledge files for correctness.** It checks whether
  the index matches them. Both can be wrong together, in the same way, and
  nothing here will notice.

## Uninstalling

Delete the files you added and remove the `hooks` block. That is the whole
procedure — no state is written outside `.state/`, which is gitignored and
regenerable, and no existing file was modified at any point.
