#!/usr/bin/env python3
"""build_index.py — compress the knowledge sources into one small JSON index.

Why this exists
---------------
Loading every source file at session start is the most expensive thing a
harness does, and most of the cost is repetition: the same constraints, the
same style rules, read again in full every time. This reduces the source
directory to a compact index — a few hundred tokens instead of tens of
thousands — and, more importantly, records the mtime of every source it read.

That recorded mtime is the whole trick. It turns "is the index still true?"
from a judgement call into an integer comparison, which is what
`freshness_check.py` performs. The index is not trusted; it is *dated*.

Layout
------
    {
      "_meta": {"v": 1, "bt": "<iso8601>", "ttl": <seconds>,
                "sm": {<basename>: <mtime>},        # source mtimes, recorded
                "_paths": {<basename>: <relpath>}}, # where to re-check them
      "sr": [{"w":..., "u":..., "a":...}],          # style rules
      "c":  [{"id":..., "t":..., "r":..., "pl":...}],# constraints
      "p":  {...},                                   # profile facts
      "s":  {"sr": n, "c": n}                        # summary counts
    }

Usage
-----
    python scripts/build_index.py --build
    python scripts/build_index.py --stats

Exit codes: 0 written, 2 could not write.
"""
import argparse
import glob
import json
import os
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _paths  # noqa: E402

STYLE_RULE_RE = re.compile(
    r"^-\s*WHEN\s+(?P<w>.+?)\s*→\s*USE\s+(?P<u>.+?)\s*→\s*AVOID\s+(?P<a>.+?)\s*$"
)
CONSTRAINT_RE = re.compile(
    r"^-\s*\[(?P<t>HARD|SOFT)\]\s+(?P<r>.+?)(?:\s*\(source:\s*(?P<src>[^)]+)\))?\s*$"
)
FACT_RE = re.compile(r"^-\s*\*\*(?P<k>[^*]+)\*\*\s*:\s*(?P<v>.+?)\s*$")


def estimate_tokens(text):
    """Rough count: ~4 chars per token for ASCII, ~1.5 for CJK."""
    if not text:
        return 0
    cjk = len(re.findall(r"[　-鿿＀-￯]", text))
    return int((len(text) - cjk) / 4 + cjk / 1.5)


def iter_content_lines(text):
    """Yield lines that are not inside a fenced code block.

    Documentation about a rule format contains examples of that format. Those
    examples must not be parsed as rules — the first run of this script counted
    one, which is the entire reason this function exists.
    """
    fenced = False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            fenced = not fenced
            continue
        if not fenced:
            yield line


def parse_style_rules(text):
    rules = []
    for line in iter_content_lines(text):
        m = STYLE_RULE_RE.match(line.strip())
        if m:
            rules.append({"w": m.group("w"), "u": m.group("u"), "a": m.group("a")})
    return rules


def parse_constraints(text):
    out = []
    counters = {"HARD": 0, "SOFT": 0}
    for line in iter_content_lines(text):
        m = CONSTRAINT_RE.match(line.strip())
        if not m:
            continue
        tier = m.group("t")
        counters[tier] += 1
        entry = {
            "id": "%s%d" % (tier[0], counters[tier]),
            "t": tier,
            "r": m.group("r").strip(),
            "pl": None,  # filled in by the caller with the source basename
        }
        if m.group("src"):
            entry["src"] = m.group("src").strip()
        out.append(entry)
    return out


def parse_profile(text):
    profile = {}
    for line in text.splitlines():
        m = FACT_RE.match(line.strip())
        if m:
            profile[m.group("k").strip()] = m.group("v").strip()
    return profile


def build(root, kb_dir):
    sources = sorted(glob.glob(os.path.join(kb_dir, "*.md")))
    if not sources:
        print("INDEX:ERROR:no_sources_in:%s" % os.path.relpath(kb_dir, root), file=sys.stderr)
        return None

    idx = {
        "_meta": {"v": 1, "bt": "", "ttl": 0, "sm": {}, "_paths": {}},
        "sr": [],
        "c": [],
        "p": {},
        "s": {},
    }

    for path in sources:
        name = os.path.basename(path)
        try:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            mtime = os.path.getmtime(path)
        except OSError as exc:
            print("INDEX:ERROR:unreadable:%s:%s" % (name, exc), file=sys.stderr)
            return None

        idx["_meta"]["sm"][name] = mtime
        idx["_meta"]["_paths"][name] = os.path.relpath(path, root).replace("\\", "/")

        # Dispatch on the file's own name. There is no auto-detection: a source
        # whose name does not match one of these is read for its mtime and
        # ignored for its content, which is visible in the --stats counts.
        if name == "style-rules.md":
            idx["sr"].extend(parse_style_rules(text))
        elif name == "constraints.md":
            for entry in parse_constraints(text):
                entry["pl"] = name
                idx["c"].append(entry)
        elif name == "project-profile.md":
            idx["p"].update(parse_profile(text))

    idx["_meta"]["bt"] = datetime.now(timezone.utc).isoformat()
    idx["s"] = {"sr": len(idx["sr"]), "c": len(idx["c"]), "p": len(idx["p"])}
    return idx


def write_index(root, cfg, idx):
    out = _paths.cfg_path(root, cfg, "knowledge", "index")
    idx["_meta"]["ttl"] = int(cfg["knowledge"].get("ttl_seconds", 86400))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(idx, fh, ensure_ascii=False, indent=2, sort_keys=False)
        fh.write("\n")
    os.replace(tmp, out)

    # Completion record. Distinct from the detection record that
    # freshness_check.py writes: this says "a build finished", that one says
    # "staleness was observed". The two names never converge, because a record
    # that means both tells you neither.
    record = _paths.state_file(root, cfg, "last-index-build.json")
    with open(record, "w", encoding="utf-8") as fh:
        json.dump({"ts": idx["_meta"]["bt"], "sources": len(idx["_meta"]["sm"])}, fh)
        fh.write("\n")
    return out


def cmd_stats(root, cfg):
    path = _paths.cfg_path(root, cfg, "knowledge", "index")
    if not os.path.exists(path):
        print("INDEX:ERROR:no_index_run_build_first", file=sys.stderr)
        return 2
    try:
        with open(path, encoding="utf-8") as fh:
            idx = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        print("INDEX:ERROR:corrupt:%s" % exc, file=sys.stderr)
        return 2
    print(json.dumps({
        "built_at": idx.get("_meta", {}).get("bt"),
        "sources": len(idx.get("_meta", {}).get("sm", {})),
        "style_rules": len(idx.get("sr", [])),
        "constraints": len(idx.get("c", [])),
        "profile_facts": len(idx.get("p", {})),
        "estimated_tokens": estimate_tokens(json.dumps(idx, ensure_ascii=False)),
    }, indent=2))
    return 0


def main():
    _paths.use_utf8_stdout()
    ap = argparse.ArgumentParser(description="Build or inspect the knowledge index.")
    ap.add_argument("--build", action="store_true", help="rebuild the index from sources")
    ap.add_argument("--stats", action="store_true", help="print index statistics")
    ap.add_argument("--root", default=_paths.REPO_ROOT)
    args = ap.parse_args()

    root = os.path.abspath(args.root)
    cfg = _paths.load_config(root)

    if args.stats:
        return cmd_stats(root, cfg)

    kb_dir = _paths.cfg_path(root, cfg, "knowledge", "dir")
    idx = build(root, kb_dir)
    if idx is None:
        return 2
    out = write_index(root, cfg, idx)
    print("INDEX:OK:sources=%d:sr=%d:c=%d:tok~%d:%s"
          % (len(idx["_meta"]["sm"]), len(idx["sr"]), len(idx["c"]),
             estimate_tokens(json.dumps(idx, ensure_ascii=False)),
             os.path.relpath(out, root).replace("\\", "/")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
