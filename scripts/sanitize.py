#!/usr/bin/env python3
"""sanitize.py — the publication gate.

What this is
------------
The last thing that runs before content leaves. It looks for two different
kinds of leak, and the order it looks in is the whole design:

  DIM-2  semantic. Statements that reveal authorship, attribution, or intent,
         independent of any identifier: a sentence crediting the work to
         somebody other than the person presenting it, a claim about why the
         text was written, an assertion of sole ownership.

  DIM-1  identifier. Real paths, emails, account names, key-shaped strings,
         long digit runs.

**DIM-2 runs first and is not waivable.** A DIM-1 finding can be released with
a recorded waiver, because the string is the problem and the string is known. A
DIM-2 finding cannot: the problem is the claim, and no sign-off makes a false
attribution acceptable in a published document. The only remedy is to rewrite
the sentence.

Running DIM-1 first would be worse than useless — a file whose identifiers have
been scrubbed reads as clean, which is exactly the state in which a DIM-2
statement survives review.

Why the export tree and not the working tree
--------------------------------------------
`--export-scan` runs against `git archive` output: the tree that would actually
be published. The working directory holds gitignored state, scratch files, and
build artifacts that are not going anywhere. Findings from those cannot be
acted on, and a report padded with them trains its reader to skim.

`--scan` at the repository root uses the same definition without needing a
commit: `git ls-files` filtered by the ignore rules. Scanning an arbitrary
directory outside the repository falls back to walking it.

The one suppression
-------------------
A line carrying the marker `sanitize:fixture` is not reported. It exists for
test fixtures — a guard that checks for private-key paths has to contain a
path-shaped string to test itself against, and that string is not a leak.

The marker is not free. Every run prints the number of suppressed lines, and
`scripts/selftest.py` asserts that number against a constant in the repository.
Adding a suppression therefore changes a number that a test checks, which makes
it a deliberate act rather than something typed on the way past.

Usage
-----
    python scripts/sanitize.py --scan                # this repository
    python scripts/sanitize.py --scan /some/tree     # any directory
    python scripts/sanitize.py --export-scan         # git archive HEAD
    python scripts/sanitize.py --export-scan v1.2.0  # any rev
    python scripts/sanitize.py --selftest            # prove it can go red
    python scripts/sanitize.py --denylist .denylist  # extra literal terms

Exit 0 clean, exit 2 on any DIM-2 finding or any unwaived DIM-1 finding.
"""
import argparse
import os
import re
import subprocess
import sys
import tarfile
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _paths  # noqa: E402

SKIP_DIRS = {".git", ".state", "__pycache__", ".pytest_cache", ".mypy_cache"}
SKIP_EXT = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".gz",
            ".tar", ".db", ".sqlite", ".woff", ".woff2", ".ttf", ".pyc"}
MAX_BYTES = 4 * 1024 * 1024  # a 4MB text file is not a source file; skip it

FIXTURE_MARKER = "sanitize:fixture"

# --- DIM-2 · semantic. Not waivable. ----------------------------------------
DIM2_RULES = [
    ("ATTRIBUTION", re.compile(
        r"actually\s+(?:someone|somebody)\s+else'?s"
        r"|was\s+asked\s+to\s+(?:claim|present|submit|sign)"
        r"|asked\s+me\s+to\s+(?:claim|present|submit|sign)"
        r"|credit\s+(?:for\s+[^.\n]{0,40}?)?goes\s+to"
        r"|(?:not|isn'?t)\s+my\s+(?:work|design|idea|code)"
        r"|(?:someone|somebody)\s+else'?s\s+work", re.IGNORECASE)),
    ("INTERNAL_MOTIVE", re.compile(
        r"\blooks\s+good\s+to\s+the\s+(?:recruiter|interviewer|hiring)"
        r"|\bfor\s+the\s+(?:recruiter|interviewer|hiring\s+manager)"
        r"|\bfor\s+my\s+resume\b"
        r"|\bto\s+impress\s+the\s+(?:recruiter|interviewer)", re.IGNORECASE)),
    ("OWNERSHIP", re.compile(
        r"\bI\s+(?:built|wrote|designed|created|own|made|developed|authored)\b"
        r"|\bmy\s+(?:own\s+)?system\b", re.IGNORECASE)),
]
# PERSON_DRIFT needs two signals in one document, so it is not a single regex.
THIRD_PERSON_SELF = re.compile(r"\b(?:the\s+author|the\s+owner|the\s+developer)\b",
                               re.IGNORECASE)
FIRST_PERSON = re.compile(r"\b(?:I|me|my|mine)\b")

# --- DIM-1 · identifier. Waivable with SANITIZE_WAIVED=1. --------------------
DIM1_RULES = [
    ("HOME_PATH", re.compile(
        r"[A-Za-z]:[\\/]Users[\\/][^\\/\s\"']+"
        r"|/(?:home|Users)/[^/\s\"']+", re.IGNORECASE)),
    ("EMAIL", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("PRIVATE_KEY", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("SECRET", re.compile(
        r"\b(?:sk|pk|rk)-[A-Za-z0-9_-]{16,}"
        r"|\bgh[pousr]_[A-Za-z0-9]{16,}"
        r"|\bxox[baprs]-[A-Za-z0-9-]{10,}"
        r"|\bAKIA[0-9A-Z]{12,}"
        r"|\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\."
        r"|(?:api[_-]?key|secret|token|passwd|password)\s*[:=]\s*[\"']?[^\s\"']{8,}",
        re.IGNORECASE)),
    ("DIGIT_RUN", re.compile(r"\b\d{10,}\b")),
]


def detect(text, denylist=()):
    """Return (findings, suppressed) for one chunk of text.

    Each finding is (dim, class, lineno, sample). Line-oriented so a finding
    can name the line it came from; the whole-document rule (person drift) is
    evaluated over the whole chunk and carries lineno 0.
    """
    findings, suppressed = [], []
    for lineno, line in enumerate(text.splitlines(), 1):
        on_line = []
        for cls, pattern in DIM2_RULES:
            m = pattern.search(line)
            if m:
                on_line.append(("DIM-2", cls, lineno, m.group(0)))
        for cls, pattern in DIM1_RULES:
            m = pattern.search(line)
            if m:
                on_line.append(("DIM-1", cls, lineno, m.group(0)))
        for term in denylist:
            if term and term in line:
                on_line.append(("DIM-1", "DENYLIST", lineno, term))
        if FIXTURE_MARKER in line:
            suppressed.extend(on_line)
        else:
            findings.extend(on_line)
    if THIRD_PERSON_SELF.search(text) and FIRST_PERSON.search(text):
        m = THIRD_PERSON_SELF.search(text)
        findings.append(("DIM-2", "PERSON_DRIFT", 0, m.group(0)))
    return findings, suppressed


def load_denylist(path):
    """A plain list of literal terms, one per line.

    Kept out of the repository on purpose: the list of names that must not be
    published is itself a list of those names. `.denylist` is gitignored, and
    the repository ships only the pattern classes above.
    """
    if not path:
        return []
    if not os.path.exists(path):
        raise SystemExit("SANITIZE:ERROR:denylist_missing:%s" % path)
    with open(path, encoding="utf-8") as fh:
        return [ln.strip() for ln in fh
                if ln.strip() and not ln.lstrip().startswith("#")]


def git_visible_files(root):
    """The files git would publish from *this* directory: tracked, plus
    untracked minus ignored.

    Returns None when root is not the top of its own repository, and the caller
    falls back to walking. That guard matters: this directory may sit inside a
    larger repository — a home directory that is itself version-controlled is
    the common case — and `git ls-files` there would answer a question about
    the outer repository while looking like it answered one about this tree.
    """
    try:
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                             cwd=root, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL)
        if top.returncode != 0:
            return None
        found = top.stdout.decode("utf-8", "ignore").strip()
        if os.path.normcase(os.path.abspath(found)) != os.path.normcase(root):
            return None
        proc = subprocess.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=root, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    names = proc.stdout.decode("utf-8", "ignore").split("\0")
    return [n for n in names if n]


def iter_files(root, skip_corpus=False, skip_paths=()):
    """Yield files under root, using git's ignore rules when it can."""
    skipped = {os.path.normcase(os.path.abspath(p)) for p in skip_paths}
    visible = git_visible_files(root)
    if visible is not None:
        for name in visible:
            rel = name.replace("\\", "/")
            if skip_corpus and (rel == "corpus" or rel.startswith("corpus/")):
                continue
            if os.path.splitext(rel)[1].lower() in SKIP_EXT:
                continue
            path = os.path.join(root, name)
            if os.path.normcase(os.path.abspath(path)) in skipped:
                continue
            try:
                if os.path.getsize(path) > MAX_BYTES:
                    continue
            except OSError:
                continue
            yield path
        return

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        if skip_corpus:
            rel_dir = os.path.relpath(dirpath, root).replace(os.sep, "/")
            if rel_dir == "corpus" or rel_dir.startswith("corpus/"):
                dirnames[:] = []
                continue
        for name in filenames:
            if os.path.splitext(name)[1].lower() in SKIP_EXT:
                continue
            path = os.path.join(dirpath, name)
            if os.path.normcase(os.path.abspath(path)) in skipped:
                continue
            try:
                if os.path.getsize(path) > MAX_BYTES:
                    continue
            except OSError:
                continue
            yield path


def scan_tree(root, denylist=(), skip_corpus=False, skip_paths=()):
    hits, suppressed, files = [], [], 0
    for path in iter_files(root, skip_corpus, skip_paths):
        try:
            with open(path, encoding="utf-8", errors="ignore") as fh:
                text = fh.read()
        except OSError:
            continue
        files += 1
        rel = os.path.relpath(path, root).replace(os.sep, "/")
        found, held = detect(text, denylist)
        for dim, cls, lineno, sample in found:
            hits.append((dim, cls, rel, lineno, sample))
        for dim, cls, lineno, sample in held:
            suppressed.append((dim, cls, rel, lineno, sample))
    return hits, suppressed, files


def export_tree(root, rev):
    """Materialise `git archive <rev>` into a temporary directory."""
    tmp = tempfile.mkdtemp(prefix="sanitize-export-")
    tar_path = os.path.join(tmp, "export.tar")
    try:
        subprocess.run(["git", "archive", "--format=tar", "-o", tar_path, rev],
                       cwd=root, check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        detail = getattr(exc, "stderr", b"") or b""
        raise SystemExit("SANITIZE:ERROR:git_archive_failed:%s:%s"
                         % (rev, detail.decode("utf-8", "ignore").strip() or exc))
    dest = os.path.join(tmp, "tree")
    os.makedirs(dest, exist_ok=True)
    with tarfile.open(tar_path) as tf:
        try:
            tf.extractall(dest, filter="data")
        except TypeError:  # `filter` arrived in 3.12; older interpreters
            tf.extractall(dest)
    return dest


def report(hits, suppressed, files, waived):
    dim2 = [h for h in hits if h[0] == "DIM-2"]
    dim1 = [h for h in hits if h[0] == "DIM-1"]
    for dim, cls, rel, lineno, sample in dim2 + dim1:
        where = "%s:%d" % (rel, lineno) if lineno else rel
        sample = sample if len(sample) <= 70 else sample[:67] + "..."
        if dim == "DIM-2":
            tag = "DIM-2/NOT-WAIVABLE"
        else:
            tag = "DIM-1/waived" if waived else "DIM-1"
        print("  %-18s %-14s %s  %s" % (tag, cls, where, sample))
    status = "FAIL" if (dim2 or (dim1 and not waived)) else "PASS"
    print("SANITIZE:%s:dim2=%d:dim1=%d:suppressed=%d:files=%d"
          % (status, len(dim2), len(dim1), len(suppressed), files))
    for dim, cls, rel, lineno, _sample in suppressed:
        print("  suppressed (fixture)  %-14s %s:%s" % (cls, rel, lineno))
    if dim2:
        print("  DIM-2 cannot be waived. Rewrite the statement; do not release it.",
              file=sys.stderr)
    elif dim1 and not waived:
        print("  Re-run with SANITIZE_WAIVED=1 to release the DIM-1 findings, "
              "having read each one.", file=sys.stderr)
    return 2 if (dim2 or (dim1 and not waived)) else 0


def run_selftest(root):
    """Every should-fail line must be caught. Every CLEAN line must not.

    A corpus that produces no failures is treated as a failure, not a pass: a
    gate that cannot be shown to go red has not been shown to do anything.
    """
    corpus = os.path.join(root, "corpus", "should_fail.txt")
    if not os.path.exists(corpus):
        print("SANITIZE:SELFTEST:FAIL:corpus_missing:%s" % corpus, file=sys.stderr)
        return 2
    with open(corpus, encoding="utf-8") as fh:
        lines = fh.read().splitlines()

    expected = clean = caught = missed = false_positive = 0
    for lineno, raw in enumerate(lines, 1):
        if "::" not in raw or raw.lstrip().startswith("#"):
            continue
        cls, sample = raw.split("::", 1)
        cls = cls.strip()
        found, _held = detect(sample)
        if cls == "CLEAN":
            clean += 1
            if found:
                false_positive += 1
                print("SANITIZE:SELFTEST:FAIL:clean_line_flagged:%d:%s"
                      % (lineno, found[0][1]), file=sys.stderr)
            continue
        expected += 1
        if any(f[1] == cls for f in found):
            caught += 1
        else:
            missed += 1
            print("SANITIZE:SELFTEST:MISS:%d:%s (nothing fired)" % (lineno, cls))

    if expected == 0:
        print("SANITIZE:SELFTEST:FAIL:corpus_has_no_should_fail_lines",
              file=sys.stderr)
        return 2
    if missed or false_positive:
        print("SANITIZE:SELFTEST:FAIL:missed=%d:false_positives=%d"
              % (missed, false_positive), file=sys.stderr)
        return 2
    print("SANITIZE:SELFTEST:PASS:caught=%d:clean=%d" % (caught, clean))
    return 0


def main():
    _paths.use_utf8_stdout()
    ap = argparse.ArgumentParser(description="Publication gate: DIM-2 then DIM-1.")
    ap.add_argument("--root", default=_paths.REPO_ROOT)
    ap.add_argument("--scan", nargs="?", const=".", default=None, metavar="DIR",
                    help="scan a directory (default: this repository)")
    ap.add_argument("--export-scan", nargs="?", const="HEAD", default=None,
                    metavar="REV", help="scan `git archive REV` (default HEAD)")
    ap.add_argument("--denylist", default=None, metavar="FILE",
                    help="literal terms to reject, one per line; gitignored")
    ap.add_argument("--selftest", action="store_true",
                    help="require corpus/should_fail.txt to be fully caught")
    args = ap.parse_args()

    root = os.path.abspath(args.root)

    if args.selftest:
        return run_selftest(root)

    denylist = load_denylist(args.denylist)
    waived = os.environ.get("SANITIZE_WAIVED") == "1"

    # Derived files are excluded whether or not the ignore rules are in play.
    # Their contents are regenerated from the sources beside them, so a hit in
    # one is a hit in the source, reported twice.
    cfg = _paths.load_config(root)
    derived = [_paths.cfg_path(root, cfg, "knowledge", "index"),
               _paths.cfg_path(root, cfg, "assets", "db")]

    if args.export_scan is not None:
        tree = export_tree(root, args.export_scan)
        # This repository's corpus/ is supposed to be dirty — it is the
        # negative control, and it is in .gitignore for exactly that reason.
        hits, suppressed, files = scan_tree(tree, denylist, skip_corpus=True)
        print("SANITIZE:export-scan:%s:files=%d" % (args.export_scan, files))
    else:
        target = os.path.abspath(args.scan if args.scan else root)
        hits, suppressed, files = scan_tree(target, denylist,
                                            skip_corpus=(target == root),
                                            skip_paths=derived)
        print("SANITIZE:scan:%s:files=%d" % (target, files))

    return report(hits, suppressed, files, waived)


if __name__ == "__main__":
    sys.exit(main())
