#!/usr/bin/env python3
"""evidence_gate.py — you may not write a claim about a source you never read.

The failure this prevents
-------------------------
A model (or a person) writing from memory produces a confident sentence about
something it half-remembers. The sentence is fluent, which is exactly what makes
it dangerous: nothing about the prose reveals that the underlying file was never
opened. The check is blunt and it works — if the topic is about X, the file that
defines X must appear in this session's read history.

How it works
------------
Two trigger tables map a write onto the evidence it requires:

  * `CONTENT_TRIGGERS` — if the text being written matches a pattern, the
    named source files must have been read.
  * `PATH_TRIGGERS`    — if the file being written matches a pattern, likewise.

Read history comes from the session transcript: every `Read` tool call recorded
in it. Zero natural-language understanding, one regex match and one set lookup.

Two properties worth keeping if you rewrite this
------------------------------------------------
  * **Fail-open.** If the transcript is missing or unreadable, the gate returns
    0. A gate that blocks when it cannot see is a gate that blocks everything
    the moment the plumbing changes. Better to miss than to wedge.
  * **Self-reference exemption.** A file cannot be evidence for itself. Requiring
    that `constraints.md` be read before `constraints.md` may be written is a
    loop that can never be satisfied, and it is the single largest source of
    false positives this kind of gate produces.

The trigger values below are demo data. Replace them with the topics of the
documents you actually write.

Hook contract (Claude Code `PreToolUse`, matcher `Write|Edit`)
    stdin   {"tool_name","tool_input","transcript_path","agent_id"}
    exit 2  BLOCK; exit 0 pass or no trigger matched.
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _paths  # noqa: E402

# --- Demo trigger tables ----------------------------------------------------

CONTENT_TRIGGERS = [
    # Regex matched against the text being written -> required sources.
    (r"(?i)\b(deploy|rollback|release window|blue[- ]green)\b",
     ["knowledge/constraints.md"]),
    (r"(?i)\b(tone|wording|style rule|phrasing)\b",
     ["knowledge/style-rules.md"]),
    (r"(?i)\b(idempotency|single writer|sharp edge)\b",
     ["knowledge/project-profile.md"]),
]

PATH_TRIGGERS = [
    # Regex matched against the target path -> required sources.
    (r"(?i)(report|summary|review)\.md$", ["knowledge/project-profile.md"]),
]

# Paths that are never gated: they are harness plumbing, not claims about the
# world, and gating them creates a false positive on every internal edit.
FAST_PASS_MARKERS = ("/scripts/", "/.state/", "/corpus/", "/.git/")


def normalize(path):
    return path.replace("\\", "/")


def scan_transcript(transcript_path):
    """Return the set of file paths Read in this session, or None if unavailable.

    None means "could not look", which is different from "looked and found
    nothing". The caller treats them differently: the first passes, the second
    blocks.
    """
    if not transcript_path:
        return None
    path = os.path.expanduser(transcript_path)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError:
        return None

    read_files = set()
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("type") != "assistant":
            continue
        content = obj.get("message", {}).get("content", [])
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            if block.get("name") != "Read":
                continue
            read_path = block.get("input", {}).get("file_path", "")
            if read_path:
                read_files.add(normalize(read_path))
    return read_files


def resolve_subagent_transcript(parent_path, agent_id):
    """Find a subagent's own transcript.

    A subagent's Read calls land in its own transcript, while the hook payload
    points at the parent's. Without this, every subagent is structurally
    blocked: it reads the source, retries, and is blocked again, because the
    parent transcript it is being judged against never contained that read.
    """
    if not parent_path or not agent_id:
        return None
    session_dir = os.path.splitext(os.path.expanduser(parent_path))[0]
    sub_dir = os.path.join(session_dir, "subagents")
    if not os.path.isdir(sub_dir):
        return None
    exact = os.path.join(sub_dir, "agent-%s.jsonl" % agent_id)
    if os.path.exists(exact):
        return exact
    for name in os.listdir(sub_dir):
        if name.endswith(".jsonl") and agent_id in name:
            return os.path.join(sub_dir, name)
    return None


def check_evidence(content_text, file_path, read_files):
    """Return (missing_sources, fired_triggers)."""
    target = normalize(file_path)
    required, fired = set(), []

    for index, (pattern, sources) in enumerate(PATH_TRIGGERS):
        if re.search(pattern, target):
            required.update(sources)
            fired.append("path[%d]" % index)

    if content_text:
        for index, (pattern, sources) in enumerate(CONTENT_TRIGGERS):
            m = re.search(pattern, content_text)
            if m:
                required.update(sources)
                # Record *which word* fired, not just which file is missing. A
                # gate log that cannot tell you why the gate fired cannot be
                # tuned, and an untunable gate gets disabled.
                fired.append("content[%d]:%s" % (index, m.group(0)[:40]))

    missing = []
    for source in sorted(required):
        if source in target:
            continue  # self-reference: a file is not evidence for itself
        if not any(source in read for read in read_files):
            missing.append(source)
    return missing, fired


def log_firing(root, cfg, event, detail):
    try:
        with open(_paths.state_file(root, cfg, "gates.jsonl"), "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"gate": "evidence-gate", "event": event,
                                 "detail": detail}) + "\n")
    except OSError:
        pass


def run_selftest():
    """Prove the gate can go red and can go green, without a session."""
    trigger_text = "We will roll back the release if the blue-green cutover fails."
    clean_text = "The index records the mtime of every source it read."
    required = "knowledge/constraints.md"

    missing, fired = check_evidence(trigger_text, "docs/notes.md", set())
    if not missing:
        print("EVIDENCE-GATE:SELFTEST:FAIL:trigger text did not require its source", file=sys.stderr)
        return 2

    missing_ok, _ = check_evidence(trigger_text, "docs/notes.md", {"example/" + required})
    if missing_ok:
        print("EVIDENCE-GATE:SELFTEST:FAIL:source read but still blocked", file=sys.stderr)
        return 2

    missing_clean, fired_clean = check_evidence(clean_text, "docs/notes.md", set())
    if missing_clean or fired_clean:
        print("EVIDENCE-GATE:SELFTEST:FAIL:clean text fired %s" % fired_clean, file=sys.stderr)
        return 2

    missing_self, _ = check_evidence("rollback", "example/knowledge/constraints.md", set())
    if missing_self:
        print("EVIDENCE-GATE:SELFTEST:FAIL:self-reference not exempt", file=sys.stderr)
        return 2

    print("EVIDENCE-GATE:SELFTEST:PASS:blocks=%s:clean=ok:self_reference=ok" % required)
    return 0


def main():
    _paths.use_utf8_stdout()
    ap = argparse.ArgumentParser(description="Require source evidence before a write lands.")
    ap.add_argument("--root", default=_paths.REPO_ROOT)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return run_selftest()

    root = os.path.abspath(args.root)
    cfg = _paths.load_config(root)

    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return 0
        payload = json.loads(raw)
    except (json.JSONDecodeError, OSError):
        return 0

    if payload.get("tool_name") not in ("Write", "Edit"):
        return 0

    tool_input = payload.get("tool_input", {})
    file_path = tool_input.get("file_path", "")
    if not file_path or not file_path.lower().endswith(".md"):
        return 0

    target = normalize(file_path)
    if any(marker in target for marker in FAST_PASS_MARKERS):
        return 0

    content_text = tool_input.get("content", "") if payload["tool_name"] == "Write" \
        else tool_input.get("new_string", "")

    transcript_path = payload.get("transcript_path", "")
    agent_id = payload.get("agent_id", "") or ""
    if agent_id:
        sub = resolve_subagent_transcript(transcript_path, agent_id)
        if not sub:
            return 0  # fail-open, same as an unavailable parent transcript
        transcript_path = sub

    read_files = scan_transcript(transcript_path)
    if read_files is None:
        return 0  # could not look

    missing, fired = check_evidence(content_text, file_path, read_files)
    if missing:
        print("\n[EVIDENCE-GATE] BLOCK — source evidence not loaded", file=sys.stderr)
        print("  file: %s" % file_path, file=sys.stderr)
        for source in missing:
            print("  missing source: %s" % source, file=sys.stderr)
        print("  action: read the file(s) above, then retry the write.", file=sys.stderr)
        log_firing(root, cfg, "blocked",
                   "file=%s fired=%s missing=%s" % (file_path, ";".join(fired), ",".join(missing)))
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
