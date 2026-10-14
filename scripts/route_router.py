#!/usr/bin/env python3
"""route_router.py — retrieve the right file before the model starts searching.

The idea
--------
Deciding which file is relevant is a retrieval problem, and retrieval does not
need a language model. Matching a trigger word against a keyword list is a
substring test. Doing it in a script means the model receives the answer
instead of the task: one injected pointer, no exploratory tool calls, no round
trips.

The two cost properties that matter:

  * **A miss costs nothing.** No match means no output. An empty injection adds
    zero tokens to the context. The router is therefore free to be imperfect —
    a wrong guess is expensive, a missed guess is merely one of the many
    searches you were going to do anyway.
  * **The output is capped.** At most four pointers, routes before assets,
    duplicates collapsed. Retrieval that returns twenty candidates has not
    answered anything.

Hook contract (Claude Code `UserPromptSubmit`)
---------------------------------------------
    stdin   {"prompt": "<the user's message>"}
    stdout  the block to inject; empty when nothing matched

Local use
---------
    python scripts/route_router.py --test
    echo '{"prompt":"how do I roll back a release"}' | python scripts/route_router.py
    python scripts/route_router.py "who owns helios"

Exit codes: 0 always (a router that fails a session because it had no match
would be worse than useless). `--test` exits 2 when the bar is not met, because
a test is a gate and gates have a failing state.
"""
import argparse
import json
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _paths  # noqa: E402
from build_assets_db import parse_routes  # noqa: E402

CAP = 4


def load_routes(root, cfg):
    """Prefer the built database; fall back to parsing the markdown directly.

    The fallback is not a convenience — it is what makes the router usable
    before anything has been built. A component that only works after a build
    step is a component nobody runs.
    """
    db_path = _paths.cfg_path(root, cfg, "assets", "db")
    if os.path.exists(db_path):
        try:
            con = sqlite3.connect(db_path)
            rows = con.execute("SELECT kw, load_path FROM routes").fetchall()
            con.close()
            if rows:
                return rows, "data-assets.db"
        except sqlite3.Error:
            pass
    memory = _paths.cfg_path(root, cfg, "assets", "routes_source")
    return parse_routes(memory), os.path.basename(memory)


def load_assets(root, cfg):
    db_path = _paths.cfg_path(root, cfg, "assets", "db")
    if not os.path.exists(db_path):
        return []
    try:
        con = sqlite3.connect(db_path)
        rows = con.execute(
            "SELECT name, path, dtype, tags FROM assets WHERE tags != ''").fetchall()
        con.close()
        return rows
    except sqlite3.Error:
        return []


def match_routes(message, routes):
    """Substring match, ranked by how specific the hit was.

    Ranking by number of keywords hit and then by the length of the longest one
    is what stops a broad trigger ("style") from outranking a narrow one
    ("sharp edge") when both fire.
    """
    hits = []
    for keywords, target in routes:
        matched = [k for k in keywords.split(",") if k and k in message]
        if matched:
            hits.append((len(matched), max(len(k) for k in matched), matched, target))
    hits.sort(key=lambda x: (-x[0], -x[1]))
    return hits


def match_assets(message, assets):
    hits = []
    for name, path, dtype, tags in assets:
        matched = [t for t in tags.split(",") if t and t in message]
        if matched:
            hits.append((len(matched), max(len(t) for t in matched), name, path, dtype))
    hits.sort(key=lambda x: (-x[0], -x[1]))
    return hits


def inject(message, routes, assets):
    """Build the injected block: routes first, then assets, at most CAP lines."""
    lines, seen, same_sig = [], set(), {}
    for item in (match_routes(message, routes) + match_assets(message, assets)):
        if len(item) == 4:
            _, _, matched, target = item
            if target in seen:
                continue
            sig = tuple(sorted(matched))
            same_sig[sig] = same_sig.get(sig, 0) + 1
            if same_sig[sig] > 1:
                continue  # one pointer per keyword set; the second is noise
            seen.add(target)
            lines.append("  -> %s => %s" % (",".join(matched), target))
        else:
            _, _, name, path, dtype = item
            if path in seen:
                continue
            seen.add(path)
            lines.append("  -> [%s] %s => %s" % (dtype, name, path))
        if len(lines) >= CAP:
            break
    return lines


# --- Falsification cases ----------------------------------------------------
#
# These are not unit tests of the matcher; they are tests of the *routing table*.
# A keyword that exists but leads nowhere is indistinguishable from a working
# one until someone tries it. Each case is a plausible way a person would ask,
# followed by fragments that must appear in the injected block.
#
# The bar is 7/10 rather than 10/10 on purpose: routing is fuzzy, and a table
# tuned until every invented case passes is a table tuned to the invented cases.

POPPER_CASES = [
    ("how do I roll back a release", ["knowledge/constraints.md"]),
    ("what is the events endpoint schema", ["knowledge/project-profile.md"]),
    ("was there an incident last night", ["knowledge/constraints.md"]),
    ("who owns helios", ["knowledge/project-profile.md"]),
    ("the end-to-end test is flaky again", ["knowledge/project-profile.md"]),
    ("what are the hard rules here", ["knowledge/constraints.md"]),
    ("any known sharp edges", ["knowledge/project-profile.md"]),
    ("what tone should the docs use", ["knowledge/style-rules.md"]),
    ("what shipped in the last release", ["docs/releases.md"]),
    ("where are the postmortems kept", ["docs/postmortems"]),
]

# Prompts that must produce nothing at all. If the router answers one of these,
# it is matching too eagerly, and every miss-turned-hit costs context.
NEGATIVE_CASES = [
    "write a haiku about the weather",
    "what is 17 times 23",
]


def run_test(root, cfg):
    routes, src = load_routes(root, cfg)
    assets = load_assets(root, cfg)
    if not routes and not assets:
        print("ROUTE:TEST:ERROR:no_routing_data", file=sys.stderr)
        return 2

    passed = 0
    print("routing table cases (source: %s, %d routes, %d assets)" % (src, len(routes), len(assets)))
    for message, expected in POPPER_CASES:
        block = " | ".join(inject(message, routes, assets))
        ok = any(fragment in block for fragment in expected)
        passed += ok
        print("  %s %s" % ("PASS" if ok else "MISS", message))
        if not ok:
            print("       wanted one of: %s" % ", ".join(expected))
            print("       got: %s" % (block or "(empty)"))

    print("\nnegative cases (must inject nothing):")
    negatives_ok = True
    for message in NEGATIVE_CASES:
        block = inject(message, routes, assets)
        if block:
            negatives_ok = False
            print("  FAIL %s -> injected %d line(s)" % (message, len(block)))
        else:
            print("  PASS %s -> empty" % message)

    print("\npositive: %d/%d" % (passed, len(POPPER_CASES)))
    bar_met = passed >= 7 and negatives_ok
    print("ROUTE:TEST:%s" % ("PASS" if bar_met else "FAIL"))
    return 0 if bar_met else 2


def main():
    _paths.use_utf8_stdout()
    ap = argparse.ArgumentParser(description="Mechanical routing into the context.")
    ap.add_argument("message", nargs="?", default=None)
    ap.add_argument("--root", default=_paths.REPO_ROOT)
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--explain", action="store_true",
                    help="print route/asset counts to stderr (local debugging)")
    args = ap.parse_args()

    root = os.path.abspath(args.root)
    cfg = _paths.load_config(root)

    if args.test:
        return run_test(root, cfg)

    message = args.message
    if message is None and not sys.stdin.isatty():
        raw = sys.stdin.read().strip()
        if raw.startswith("{"):
            try:
                message = json.loads(raw).get("prompt", "")
            except json.JSONDecodeError:
                message = raw
        elif raw:
            message = raw
    if not message:
        sys.stderr.write("route_router: no message on stdin or argv\n")
        return 0

    routes, src = load_routes(root, cfg)
    assets = load_assets(root, cfg)
    lines = inject(message, routes, assets)

    if not lines:
        # Empty stdout is the contract. It means "nothing matched", which the
        # caller must treat as zero injected tokens, not as an error.
        if args.explain:
            sys.stderr.write("route_router: no match (source=%s)\n" % src)
        return 0

    sys.stdout.write("[route-router] mechanical injection (do not search):\n")
    sys.stdout.write("\n".join(lines) + "\n")
    if args.explain:
        sys.stderr.write("route_router: %d line(s) from %s\n" % (len(lines), src))
    return 0


if __name__ == "__main__":
    sys.exit(main())
