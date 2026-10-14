#!/usr/bin/env python3
"""claim_gate.py — a claim of success is a commitment, and commitments are checked.

The problem
-----------
"Done" is cheap to type and expensive to be wrong about. The usual failure is
not a lie; it is an artifact that exists but does not say what the author
believes it says — a results file with three rows, a report with no conclusion,
a config that was regenerated instead of preserved.

The mechanism
-------------
Before doing the work, declare what would have to be true for it to count:

    <!-- claim-gate:exists:example/knowledge/style-rules.md -->
    <!-- claim-gate:count:example/knowledge/style-rules.md:WHEN:8 -->
    <!-- claim-gate:lines:example/knowledge/constraints.md:20 -->
    <!-- claim-gate:contains:example/knowledge/project-profile.md:idempotency -->
    <!-- claim-gate:unchanged:example/data-catalog.example.json -->

Then the gate checks them against the filesystem, mechanically.

The important asymmetry: **PASS means "not disproven", not "complete."** A file
that exists may still be wrong. But a file that does not exist is definitely
not done. The gate is only ever allowed to be certain in the negative, which is
exactly the direction where certainty is available.

Declarations can also live in YAML frontmatter (`verify:` with a list of
`{type, path, ...}` mappings) if PyYAML is installed; the HTML-comment form has
no dependency and is what the example uses.

Usage
-----
    python scripts/claim_gate.py                          # today's files under --path
    python scripts/claim_gate.py --all                    # ignore the recency filter
    python scripts/claim_gate.py --path example --all

Exit codes: 0 all claims pass or none exist, 2 any claim failed.
"""
import argparse
import os
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _paths  # noqa: E402

try:
    import yaml
except ImportError:  # optional; the HTML-comment form needs nothing
    yaml = None

CLAIM_RE = re.compile(r"<!--\s*claim-gate:(\w+):(.*?)\s*-->")
LEGACY_RE = re.compile(r"@verify:\s*(\w+)\s+(.+?)(?:\s*$)", re.MULTILINE)
SKIP_PARTS = {".git", "__pycache__", ".state", "node_modules", ".venv"}


def resolve(path_str, origin):
    if not path_str:
        return None
    if os.path.isabs(path_str):
        return path_str
    return os.path.normpath(os.path.join(os.path.dirname(origin), path_str))


def parse_html_comments(path):
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            content = fh.read()
    except OSError:
        return []
    checks = []
    for m in CLAIM_RE.finditer(content):
        ctype = m.group(1).strip()
        parts = m.group(2).strip().split(":")
        if ctype in ("exists", "modified", "unchanged"):
            params = parts[0].strip()
        elif ctype == "lines" and len(parts) >= 2:
            params = {"path": parts[0].strip(), "min": int(parts[1])}
        elif ctype == "contains" and len(parts) >= 2:
            params = {"path": parts[0].strip(), "text": ":".join(parts[1:])}
        elif ctype == "count" and len(parts) >= 3:
            params = {"path": parts[0].strip(), "pattern": parts[1], "min": int(parts[2])}
        else:
            params = m.group(2).strip()
        checks.append({"type": ctype, "params": params, "file": path})
    return checks


def parse_frontmatter(path):
    if yaml is None:
        return []
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            content = fh.read()
    except OSError:
        return []
    if not content.startswith("---"):
        return []
    end = content.find("\n---", 3)
    if end == -1:
        return []
    try:
        fm = yaml.safe_load(content[4:end])
    except yaml.YAMLError:
        return []
    if not isinstance(fm, dict):
        return []
    entries = fm.get("verify") or fm.get("metadata", {}).get("verify")
    if not isinstance(entries, list):
        return []
    return [{"type": str(e.get("type", "")), "params": e, "file": path}
            for e in entries if isinstance(e, dict) and "type" in e]


def parse_legacy(path):
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            content = fh.read()
    except OSError:
        return []
    return [{"type": m.group(1).strip(), "params": m.group(2).strip(), "file": path}
            for m in LEGACY_RE.finditer(content)]


def parse_checks(path):
    return parse_html_comments(path) or parse_frontmatter(path) or parse_legacy(path)


# --- Handlers. Each returns (ok, message). ----------------------------------

DISPLAY_ROOT = _paths.REPO_ROOT


def _show(path):
    """Report a path relative to the project root.

    The absolute form names the machine the check ran on, and these messages
    end up pasted into logs and issue reports. A leak-prevention tool should
    not manufacture one, and a reader of the output does not need to know
    where the repository is checked out.
    """
    if not path:
        return path
    try:
        rel = os.path.relpath(path, DISPLAY_ROOT)
    except ValueError:
        return path
    return path if rel.startswith("..") else rel.replace("\\", "/")


def _target(params, origin):
    raw = params if isinstance(params, str) else params.get("path", "")
    return resolve(raw, origin)


def check_exists(params, origin, _ref_mtime):
    path = _target(params, origin)
    ok = bool(path) and os.path.exists(path)
    return ok, "%s: %s" % ("PASS" if ok else "FILE NOT FOUND", _show(path))


def check_modified(params, origin, ref_mtime):
    path = _target(params, origin)
    if not path or not os.path.exists(path):
        return False, "FILE NOT FOUND: %s" % _show(path)
    ok = os.path.getmtime(path) > ref_mtime
    return ok, "%s: %s" % ("PASS" if ok else "NOT MODIFIED SINCE THE CLAIM WAS WRITTEN",
                           _show(path))


def check_unchanged(params, origin, ref_mtime):
    path = _target(params, origin)
    if not path or not os.path.exists(path):
        return False, "FILE NOT FOUND: %s" % _show(path)
    ok = os.path.getmtime(path) <= ref_mtime
    return ok, "%s: %s" % ("PASS" if ok else "WAS MODIFIED (regression risk)", _show(path))


def check_lines(params, origin, _ref_mtime):
    if isinstance(params, dict):
        path, minimum = _target(params, origin), params.get("min", 0)
    else:
        parts = str(params).split(">=")
        if len(parts) != 2:
            return False, "INVALID FORMAT: %s" % params
        path, minimum = resolve(parts[0].strip(), origin), int(parts[1].strip())
    if not path or not os.path.exists(path):
        return False, "FILE NOT FOUND: %s" % _show(path)
    with open(path, encoding="utf-8", errors="ignore") as fh:
        actual = len(fh.read().split("\n"))
    ok = actual >= minimum
    return ok, "%s: %s (%d lines)" % ("PASS" if ok else "TOO SHORT", _show(path), actual)


def check_contains(params, origin, _ref_mtime):
    if isinstance(params, dict):
        path, needle = _target(params, origin), params.get("text", "")
    else:
        parts = str(params).split(" ", 1)
        if len(parts) != 2:
            return False, "INVALID FORMAT: %s" % params
        path, needle = resolve(parts[0].strip(), origin), parts[1].strip()
    if not path or not os.path.exists(path):
        return False, "FILE NOT FOUND: %s" % _show(path)
    with open(path, encoding="utf-8", errors="ignore") as fh:
        ok = needle in fh.read()
    return ok, "%s: %s" % ("PASS" if ok else "TEXT NOT FOUND", _show(path))


def check_count(params, origin, _ref_mtime):
    if not isinstance(params, dict):
        return False, "the count check requires the YAML form"
    path = _target(params, origin)
    if not path or not os.path.exists(path):
        return False, "FILE NOT FOUND: %s" % _show(path)
    with open(path, encoding="utf-8", errors="ignore") as fh:
        actual = fh.read().count(params.get("pattern", ""))
    minimum = params.get("min", 1)
    ok = actual >= minimum
    return ok, "%s: found %dx in %s (min %d)" % ("PASS" if ok else "TOO FEW",
                                                 actual, _show(path), minimum)


HANDLERS = {
    "exists": check_exists,
    "modified": check_modified,
    "unchanged": check_unchanged,
    "lines": check_lines,
    "contains": check_contains,
    "count": check_count,
}


def collect(scan_root, only_today=True):
    today = datetime.now(timezone.utc).date()
    found = []
    for base, dirs, files in os.walk(scan_root):
        dirs[:] = [d for d in dirs if d not in SKIP_PARTS]
        for name in files:
            if not name.endswith(".md"):
                continue
            path = os.path.join(base, name)
            if only_today:
                try:
                    if datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc).date() != today:
                        continue
                except OSError:
                    continue
            found.append(path)
    return found


def main():
    _paths.use_utf8_stdout()
    ap = argparse.ArgumentParser(description="Verify declared success criteria against the filesystem.")
    ap.add_argument("--root", default=_paths.REPO_ROOT)
    ap.add_argument("--path", default=None, help="directory to scan (default: example/)")
    ap.add_argument("--all", action="store_true", help="ignore the modified-today filter")
    args = ap.parse_args()

    root = os.path.abspath(args.root)
    global DISPLAY_ROOT
    DISPLAY_ROOT = root
    scan_root = os.path.abspath(args.path) if args.path else os.path.join(root, "example")

    if not os.path.isdir(scan_root):
        print("CLAIM:ERROR:not_a_directory:%s" % scan_root, file=sys.stderr)
        return 2

    files = collect(scan_root, only_today=not args.all)
    checks, ref_mtimes = [], {}
    for path in files:
        ref_mtimes[path] = os.path.getmtime(path)
        checks.extend(parse_checks(path))

    if not checks:
        print("CLAIM:PASS:no_claims_found")
        return 0

    results = []
    for check in checks:
        handler = HANDLERS.get(check["type"])
        if handler is None:
            results.append((check, False, "UNKNOWN TYPE: %s" % check["type"]))
            continue
        try:
            ok, message = handler(check["params"], check["file"], ref_mtimes.get(check["file"], 0))
        except Exception as exc:  # a malformed claim is a failed claim, not a crash
            ok, message = False, "ERROR: %s" % exc
        results.append((check, ok, message))

    failed = [r for r in results if not r[1]]
    for check, ok, message in results:
        print("  %s [%s] %s (%s)"
              % ("PASS" if ok else "FAIL", check["type"], message,
                 os.path.relpath(check["file"], root).replace("\\", "/")))

    if failed:
        print("CLAIM:FAIL:%d_of_%d" % (len(failed), len(results)))
        print("  -> fulfill the claim, or update the declaration.", file=sys.stderr)
        print("  -> note: PASS means 'not disproven', not 'complete'.", file=sys.stderr)
        return 2

    print("CLAIM:PASS:%d_claims_not_disproven" % len(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
