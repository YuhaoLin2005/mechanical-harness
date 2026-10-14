#!/usr/bin/env python3
"""build_assets_db.py — the asset inventory as a SQLite database.

Why a database and not a JSON file
----------------------------------
Because the queries are the point, and the queries are free. Answering "which
assets are unverified and oldest" by loading every file costs tokens and, more
expensively, costs the reader's attention. Answering it with one SELECT costs
neither. Everything cheap and mechanical belongs in SQL; only the genuinely
semantic step is allowed to touch a model.

Two tables, two different kinds of truth
----------------------------------------
    routes  — derived from the navigation index (example/MEMORY.example.md).
              Regenerable: delete it, re-parse the markdown, you get it back.
    assets  — hand-maintained in example/data-catalog.example.json. Not
              derivable from anything. If that file is lost, so is the
              inventory.

The `assets` table carries a CHECK constraint on `dtype`. That is not
decoration: it means a typo in the catalog fails the build instead of creating
a category of one that no query will ever find.

Usage
-----
    python scripts/build_assets_db.py              # rebuild
    python scripts/build_assets_db.py --demo       # rebuild, then run the demo queries
    python scripts/build_assets_db.py --query "SELECT ..."

Exit codes: 0 built or queried, 2 could not build.
"""
import argparse
import json
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _paths  # noqa: E402

DTYPES = ("identity", "capability", "evidence", "work", "knowledge",
          "relationship", "feedback", "creation", "raw", "config", "metadata")

WARM_HEADER_RE = re.compile(r"^##\s+.*\bWARM\b", re.IGNORECASE)
SECTION_RE = re.compile(r"^##\s+")
ROW_RE = re.compile(r"^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*$")

SCHEMA_ROUTES = """
CREATE TABLE routes(
    id INTEGER PRIMARY KEY,
    kw TEXT,          -- comma-separated trigger words
    load_path TEXT,   -- the one-hop destination
    tier TEXT,        -- HOT / WARM / COLD
    verified INTEGER DEFAULT 0
)"""

SCHEMA_ASSETS = """
CREATE TABLE assets(
    id INTEGER PRIMARY KEY,
    dtype TEXT,
    name TEXT,
    path TEXT,
    value TEXT,       -- one-line statement of what this asset is for
    risk TEXT,        -- what it costs to lose it, or to let it go stale
    context TEXT,     -- the occasion where it has the most value
    freshness TEXT,   -- 0d / 3d / 30d / stale / missing
    verified INTEGER DEFAULT 0,
    tags TEXT,        -- comma-separated semantic tags the router matches on
    CHECK(dtype IN ('identity','capability','evidence','work','knowledge',
                    'relationship','feedback','creation','raw','config','metadata'))
)"""


def parse_routes(memory_path):
    """Pull the WARM table out of the navigation index.

    Only WARM is read. HOT entries are loaded unconditionally, so routing to
    them would be a no-op, and COLD entries are pointers rather than
    destinations.
    """
    routes = []
    if not os.path.exists(memory_path):
        return routes
    with open(memory_path, encoding="utf-8") as fh:
        in_warm = False
        for line in fh:
            stripped = line.strip()
            if WARM_HEADER_RE.match(stripped):
                in_warm = True
                continue
            if in_warm and SECTION_RE.match(stripped):
                break
            if not in_warm:
                continue
            m = ROW_RE.match(stripped)
            if not m:
                continue
            keywords, target = m.group(1), m.group(2)
            if ".md" not in target or keywords.lower().startswith("trigger"):
                continue
            if set(keywords) <= set("-: "):
                continue  # the markdown table separator row
            keywords = [k.strip() for k in keywords.split("/") if k.strip()]
            if keywords:
                routes.append((",".join(keywords), target))
    return routes


def load_catalog(catalog_path):
    """Read the hand-maintained catalog. An unknown dtype fails the build."""
    with open(catalog_path, encoding="utf-8") as fh:
        doc = json.load(fh)
    assets = doc.get("assets", doc if isinstance(doc, list) else [])
    bad = sorted({a.get("dtype") for a in assets if a.get("dtype") not in DTYPES})
    if bad:
        raise SystemExit("DB:ERROR:unknown_dtype:%s:allowed=%s"
                         % (",".join(bad), ",".join(DTYPES)))
    return assets


def build(root, cfg):
    db_path = _paths.cfg_path(root, cfg, "assets", "db")
    routes_source = _paths.cfg_path(root, cfg, "assets", "routes_source")
    catalog = _paths.cfg_path(root, cfg, "assets", "catalog")

    if not os.path.exists(catalog):
        print("DB:ERROR:catalog_missing:%s" % os.path.relpath(catalog, root), file=sys.stderr)
        return None

    if os.path.exists(db_path):
        os.remove(db_path)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute(SCHEMA_ROUTES)
    cur.execute(SCHEMA_ASSETS)

    for kw, load_path in parse_routes(routes_source):
        cur.execute("INSERT INTO routes(kw,load_path,tier,verified) VALUES(?,?,?,0)",
                    (kw, load_path, "WARM"))

    for asset in load_catalog(catalog):
        cur.execute(
            "INSERT INTO assets(dtype,name,path,value,risk,context,freshness,verified,tags) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (asset.get("dtype"), asset.get("name", ""), asset.get("path", ""),
             asset.get("value", ""), asset.get("risk", ""), asset.get("context", ""),
             asset.get("freshness", ""), int(asset.get("verified", 0)),
             asset.get("tags", "")))

    con.commit()
    return con


DEMO_QUERIES = [
    ("A. route lookup by trigger word",
     "SELECT kw, load_path, tier FROM routes WHERE kw LIKE '%rollback%'"),
    ("B. verified evidence only",
     "SELECT dtype, name, value FROM assets WHERE dtype='evidence' AND verified=1 ORDER BY id"),
    ("C. assets whose loss is not recoverable",
     "SELECT dtype, name FROM assets WHERE risk LIKE '%not recoverable%' ORDER BY id"),
    ("D. assets at risk of going stale",
     "SELECT dtype, name, freshness FROM assets WHERE freshness IN ('30d','stale') ORDER BY id"),
    ("E. every dtype is represented",
     "SELECT dtype, COUNT(*) FROM assets GROUP BY dtype ORDER BY dtype"),
]


def run_demo(con):
    cur = con.cursor()
    for label, sql in DEMO_QUERIES:
        rows = cur.execute(sql).fetchall()
        print("\n[%s]" % label)
        print("  SQL: %s" % " ".join(sql.split()))
        for row in rows:
            print("    " + " | ".join(str(c) for c in row))
        if not rows:
            print("    (no rows)")


def main():
    _paths.use_utf8_stdout()
    ap = argparse.ArgumentParser(description="Build the asset inventory database.")
    ap.add_argument("--root", default=_paths.REPO_ROOT)
    ap.add_argument("--demo", action="store_true", help="run the sample queries after building")
    ap.add_argument("--query", default=None, help="run one SELECT against the built database")
    args = ap.parse_args()

    root = os.path.abspath(args.root)
    cfg = _paths.load_config(root)

    con = build(root, cfg)
    if con is None:
        return 2

    cur = con.cursor()
    n_routes = cur.execute("SELECT COUNT(*) FROM routes").fetchone()[0]
    n_assets = cur.execute("SELECT COUNT(*) FROM assets").fetchone()[0]

    if args.query:
        for row in cur.execute(args.query).fetchall():
            print(" | ".join(str(c) for c in row))
        con.close()
        return 0

    print("DB:OK:routes=%d:assets=%d" % (n_routes, n_assets))
    if args.demo:
        run_demo(con)
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
