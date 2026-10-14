#!/usr/bin/env python3
"""freshness_check.py — the source-to-derived staleness gate.

The problem this solves
-----------------------
A derived file (an index, a summary, a generated doc) is only an opinion about
its sources written at a moment in the past. Nothing about the derived file
tells you whether it is still true. In practice the way this fails is quiet:
the source changes, the derived file does not, and every reader keeps getting
the old answer with no indication anything is wrong.

The fix is one integer comparison per source. `build_index.py` records the
mtime of every source it read, inside the index itself. This script reads those
recorded mtimes, stats the live files, and reports any source that has moved.
No flag chain, no event plumbing, no natural-language gap — a source that is
newer than the index that claims to summarise it is stale, by definition.

Same-batch guard
----------------
A rebuild writes the index moments after reading the sources. Without a
tolerance, a build that lands inside the same filesystem timestamp tick would
report itself stale. `--min-delta` (default 60s) absorbs that: a source must be
more than a minute newer than the index to count.

Exit codes
----------
    0  fresh, or nothing to gate
    2  stale — the derived file must be rebuilt before it is trusted
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _paths  # noqa: E402


def _age_seconds(bt_iso):
    """Seconds since an ISO-8601 build time, or None if unparseable."""
    try:
        built = datetime.fromisoformat(bt_iso)
    except (TypeError, ValueError):
        return None
    if built.tzinfo is None:
        built = built.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - built).total_seconds()


def check(root, index_path, min_delta):
    """Return (stale_sources, broken_sources, ttl_expired)."""
    if not os.path.exists(index_path):
        return None  # nothing derived yet — nothing to gate

    try:
        with open(index_path, encoding="utf-8") as fh:
            idx = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        print("FRESHNESS:ERROR:index_unreadable:%s" % exc, file=sys.stderr)
        return None

    meta = idx.get("_meta", {})
    recorded = meta.get("sm", {})
    relpaths = meta.get("_paths", {})

    stale, broken = [], []
    for name, stored_mtime in recorded.items():
        rel = relpaths.get(name, name)
        path = os.path.normpath(os.path.join(root, rel))
        if not os.path.exists(path):
            # A source that cannot be found looks exactly like a source that is
            # fresh. Deleting a file must not silently satisfy the check.
            broken.append("%s:MISSING" % name)
            continue
        try:
            live = os.path.getmtime(path)
        except OSError:
            broken.append("%s:UNREADABLE" % name)
            continue
        if live - stored_mtime > min_delta:
            stale.append(name)

    ttl = int(meta.get("ttl", 0) or 0)
    age = _age_seconds(meta.get("bt", ""))
    ttl_expired = bool(ttl and age is not None and age > ttl)
    return stale, broken, ttl_expired


def main():
    _paths.use_utf8_stdout()
    ap = argparse.ArgumentParser(description="Source-to-derived freshness gate.")
    ap.add_argument("--root", default=_paths.REPO_ROOT)
    ap.add_argument("--index", default=None, help="override the index path")
    ap.add_argument("--min-delta", type=float, default=60.0,
                    help="ignore source mtimes this many seconds newer (same-batch write)")
    ap.add_argument("--no-record", action="store_true",
                    help="do not write the detection record when stale")
    args = ap.parse_args()

    root = os.path.abspath(args.root)
    cfg = _paths.load_config(root)
    index_path = args.index or _paths.cfg_path(root, cfg, "knowledge", "index")

    result = check(root, index_path, args.min_delta)
    if result is None:
        print("FRESHNESS:SKIP:no_index")
        return 0

    stale, broken, ttl_expired = result
    if not stale and not broken and not ttl_expired:
        print("FRESHNESS:OK:sources=%d" % len(
            json.load(open(index_path, encoding="utf-8")).get("_meta", {}).get("sm", {})))
        return 0

    reasons = []
    if stale:
        reasons.append("%d_sources" % len(stale))
    if broken:
        reasons.append("%d_broken" % len(broken))
    if ttl_expired:
        reasons.append("ttl_expired")

    payload = {
        "action": "rebuild",
        "derived": os.path.relpath(index_path, root).replace("\\", "/"),
        "stale_sources": stale,
        "broken_sources": broken,
        "ttl_expired": ttl_expired,
    }
    msg = "FRESHNESS:STALE:%s:%s" % (":".join(reasons), ",".join((stale + broken)[:5]))
    print(msg)
    print(msg, file=sys.stderr)
    print("FRESHNESS:JSON:" + json.dumps(payload), file=sys.stderr)
    print("  -> remedy: python scripts/build_index.py --build", file=sys.stderr)

    if not args.no_record:
        # Detection record. It says "staleness was observed at this time".
        # It deliberately does not claim a rebuild happened — that is
        # last-index-build.json, written by build_index.py. Reading one as the
        # other is the failure this separation exists to prevent.
        try:
            record = _paths.state_file(root, cfg, "freshness-stale.json")
            with open(record, "w", encoding="utf-8") as fh:
                payload["detected_at"] = datetime.now(timezone.utc).isoformat()
                json.dump(payload, fh, indent=2)
                fh.write("\n")
        except OSError as exc:
            print("FRESHNESS:WARN:record_write_failed:%s" % exc, file=sys.stderr)

    return 2


if __name__ == "__main__":
    sys.exit(main())
