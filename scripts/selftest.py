#!/usr/bin/env python3
"""selftest.py — one command that runs everything.

    python scripts/selftest.py               # everything works
    python scripts/selftest.py --expect-fail # every gate can also fail

Two different claims, and the difference is the point. The default run says the
components are consistent with each other. `--expect-fail` says the mechanisms
that are supposed to fail when something is wrong actually do — it deliberately
corrupts inputs and requires each gate to reject them.

A repository can pass the first for a long time while failing the second
completely, because a gate that has silently stopped checking is indistinguish-
able from a gate with nothing to report. Only the second run tells them apart.

Nothing here needs the network, an account, or any file outside this
repository. Exit 0 means every step behaved; exit 2 names the step that did not.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _paths  # noqa: E402

REPO_ROOT = _paths.REPO_ROOT
SCRIPTS = os.path.join(REPO_ROOT, "scripts")

# The one suppression in the repository, asserted rather than trusted.
# See scripts/sanitize.py, "The one suppression".
EXPECTED_SUPPRESSED = 1


def run(script, args=(), stdin=None, expect=0, label=None):
    """Run one script and return (ok, combined_output)."""
    cmd = [sys.executable, os.path.join(SCRIPTS, script)] + list(args)
    proc = subprocess.run(cmd, cwd=REPO_ROOT, input=stdin,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          universal_newlines=True)
    out = (proc.stdout or "").strip()
    ok = proc.returncode == expect
    name = label or ("%s %s" % (script, " ".join(args))).strip()
    if ok:
        print("  ok    %-46s exit %d" % (name, proc.returncode))
        for line in out.splitlines():
            print("          %s" % line)
    else:
        print("  FAIL  %-46s exit %d (want %d)" % (name, proc.returncode, expect))
        for line in out.splitlines():
            print("          %s" % line)
    return ok, out


def green(root):
    """The consistent-state run."""
    print("[green] every component behaves")
    checks = [
        run("build_index.py", ["--build"], label="build_index --build"),
        run("build_index.py", ["--stats"], label="build_index --stats"),
        run("freshness_check.py", label="freshness_check"),
        run("build_assets_db.py", ["--demo"], label="build_assets_db --demo"),
        run("route_router.py", ["--test"], label="route_router --test"),
        run("claim_gate.py", label="claim_gate (example/)"),
        run("evidence_gate.py", ["--selftest"], label="evidence_gate --selftest"),
        run("sensitive_path_guard.py", ["--selftest"],
            label="sensitive_path_guard --selftest"),
        run("quality_gate.py", ["--selftest"], label="quality_gate --selftest"),
        run("sanitize.py", ["--selftest"], label="sanitize --selftest"),
        run("sanitize.py", ["--scan"], label="sanitize --scan"),
    ]
    if not all(ok for ok, _ in checks):
        return False

    # The suppression count is a number a test checks, which is what keeps the
    # marker from becoming a habit.
    _, out = checks[-1]
    marker = "suppressed="
    if marker in out:
        got = int(out.split(marker, 1)[1].split(":", 1)[0])
        if got != EXPECTED_SUPPRESSED:
            print("  FAIL  sanctioned suppressions: %d, expected %d"
                  % (got, EXPECTED_SUPPRESSED))
            print("        A new `sanitize:fixture` marker was added. Update")
            print("        EXPECTED_SUPPRESSED in selftest.py and say why.")
            return False
        print("  ok    suppression count matches EXPECTED_SUPPRESSED=%d"
              % EXPECTED_SUPPRESSED)
    return True


def red(root):
    """Every gate is made to go red, then put back."""
    print("\n[red] every gate can reject bad input")
    cfg = _paths.load_config(root)
    index = _paths.cfg_path(root, cfg, "knowledge", "index")
    knowledge = _paths.cfg_path(root, cfg, "knowledge", "dir")
    ok = True

    # --- freshness_check: push a source forward, expect STALE ----------------
    src = os.path.join(knowledge, "constraints.md")
    stamp = os.path.getmtime(src)
    os.utime(src, (stamp + 3600, stamp + 3600))
    ok &= run("freshness_check.py", ["--min-delta", "0"],
              expect=2, label="freshness_check (source touched)")[0]
    # Put it back and rebuild, then require the same command to pass.
    os.utime(src, (stamp, stamp))
    ok &= run("build_index.py", ["--build"], label="build_index (restore)")[0]
    ok &= run("freshness_check.py", ["--min-delta", "0"],
              label="freshness_check (rebuilt)")[0]

    # --- evidence_gate: a claim whose source was never read ------------------
    #
    # The transcript has to exist. An unreadable transcript means the gate
    # could not look, and it fails open in that case — which is the correct
    # behaviour and therefore not the thing to test here.
    state = _paths.ensure_state_dir(root, cfg)
    transcript = os.path.join(state, "selftest-transcript.jsonl")
    unrelated = ('{"type":"assistant","message":{"content":[{"type":"tool_use",'
                 '"name":"Read","input":{"file_path":'
                 '"example/knowledge/style-rules.md"}}]}}\n')
    with open(transcript, "w", encoding="utf-8") as fh:
        fh.write(unrelated)
    payload = json.dumps({
        "tool_name": "Write",
        "tool_input": {"file_path": "notes.md",
                       "content": "The pipeline guarantees idempotency."},
        "session_id": "selftest",
        "transcript_path": transcript,
    })
    ok &= run("evidence_gate.py", stdin=payload, expect=2,
              label="evidence_gate (source not read)")[0]

    # The same payload against a transcript that does contain the read must
    # pass — otherwise the gate blocks everything and the red result above
    # would mean nothing.
    with open(transcript, "w", encoding="utf-8") as fh:
        fh.write(unrelated.replace("style-rules.md", "project-profile.md"))
    ok &= run("evidence_gate.py", stdin=payload, expect=0,
              label="evidence_gate (source read)")[0]
    os.remove(transcript)

    # An unreadable transcript must pass, not block: the gate could not look.
    payload_blind = json.dumps({
        "tool_name": "Write",
        "tool_input": {"file_path": "notes.md",
                       "content": "The pipeline guarantees idempotency."},
        "session_id": "selftest",
        "transcript_path": os.path.join(state, "no-such-transcript.jsonl"),
    })
    ok &= run("evidence_gate.py", stdin=payload_blind, expect=0,
              label="evidence_gate (blind, fails open)")[0]

    # --- sensitive_path_guard: a credential path -----------------------------
    payload = ('{"tool_name":"Write","tool_input":{"file_path":".env"}}')
    ok &= run("sensitive_path_guard.py", stdin=payload, expect=2,
              label="sensitive_path_guard (.env write)")[0]

    # --- quality_gate: a transcript with the signatures ----------------------
    sample = os.path.join(_paths.ensure_state_dir(root, cfg), "selftest-dirty.txt")
    with open(sample, "w", encoding="utf-8") as fh:
        fh.write("Everything is fixed and the migration completed successfully. "
                 "Excellent work. There was a traceback during the import; it "
                 "might have been a transient issue. The build failed once.")
    ok &= run("quality_gate.py", ["--text-file", sample], expect=2,
              label="quality_gate (dirty sample)")[0]
    os.remove(sample)

    # --- claim_gate: a declaration that is false -----------------------------
    scratch = os.path.join(_paths.ensure_state_dir(root, cfg), "selftest-claims")
    os.makedirs(scratch, exist_ok=True)
    bad = os.path.join(scratch, "bad.md")
    with open(bad, "w", encoding="utf-8") as fh:
        fh.write("# Scratch\n\n<!-- claim-gate:exists:definitely-not-here.md -->\n")
    ok &= run("claim_gate.py", ["--path", scratch, "--all"], expect=2,
              label="claim_gate (false claim)")[0]
    shutil.rmtree(scratch, ignore_errors=True)

    # --- sanitize: the real corpus, scanned as content ------------------------
    corpus = os.path.join(root, "corpus")
    ok &= run("sanitize.py", ["--scan", corpus], expect=2,
              label="sanitize --scan corpus/ (should be dirty)")[0]

    # route_router is deliberately absent: it never exits 2. A router that
    # could halt a turn is a router nobody leaves enabled. Its own --test
    # covers it in the green run.
    return bool(ok)


def main():
    _paths.use_utf8_stdout()
    ap = argparse.ArgumentParser(description="Run the whole harness.")
    ap.add_argument("--root", default=REPO_ROOT)
    ap.add_argument("--expect-fail", action="store_true",
                    help="also prove every gate can reject bad input")
    args = ap.parse_args()

    root = os.path.abspath(args.root)
    print("mechanical-harness selftest — root %s\n" % root)

    healthy = green(root)
    if args.expect_fail and healthy:
        healthy = red(root)

    if healthy:
        print("\nSELFTEST:PASS%s" % (" (including red paths)" if args.expect_fail else ""))
        return 0
    print("\nSELFTEST:FAIL", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
