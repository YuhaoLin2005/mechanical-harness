"""Shared path and configuration resolution.

Every script under scripts/ imports this. The reason is not DRY, it is that
`config.example.json` is supposed to be load-bearing. If each script
re-derived its own paths from its own constants, the config file would be
decoration: it could drift from reality and nothing would notice. Routing all
path resolution through one loader means the config file is either correct or
the scripts fail loudly.

Precedence: command-line argument > config.example.json > built-in default.

Nothing here resolves an absolute machine path. Every path in the config is
written relative to the repository root, so a fresh clone works with no edit.
"""
import json
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_NAME = "config.example.json"

DEFAULTS = {
    "knowledge": {
        "dir": "example/knowledge",
        "index": "example/knowledge-index.json",
        "ttl_seconds": 86400,
    },
    "assets": {
        "routes_source": "example/MEMORY.example.md",
        "catalog": "example/data-catalog.example.json",
        "db": "example/data-assets.db",
    },
    "gates": {
        "state_dir": ".state",
    },
}


def load_config(root=None):
    """Return the merged config (defaults < config.example.json).

    A malformed config is fatal, not silently ignored: a config that cannot be
    read would otherwise degrade every path to a default and quietly change
    what the gates are looking at.
    """
    root = root or REPO_ROOT
    cfg = json.loads(json.dumps(DEFAULTS))  # deep copy of the defaults
    path = os.path.join(root, CONFIG_NAME)
    if not os.path.exists(path):
        return cfg
    try:
        with open(path, encoding="utf-8") as fh:
            user = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        raise SystemExit("CONFIG:ERROR:unreadable:%s:%s" % (CONFIG_NAME, exc))
    if not isinstance(user, dict):
        raise SystemExit("CONFIG:ERROR:not_an_object:%s" % CONFIG_NAME)
    for section, values in user.items():
        if isinstance(values, dict) and isinstance(cfg.get(section), dict):
            cfg[section].update(values)
        else:
            cfg[section] = values
    return cfg


def cfg_path(root, cfg, *keys):
    """Resolve a config value (a repo-relative path) to an absolute path."""
    node = cfg
    for key in keys:
        if not isinstance(node, dict) or key not in node:
            raise SystemExit("CONFIG:ERROR:missing_key:%s" % ".".join(keys))
        node = node[key]
    if not isinstance(node, str):
        raise SystemExit("CONFIG:ERROR:not_a_path:%s" % ".".join(keys))
    return os.path.normpath(os.path.join(root, node))


def ensure_state_dir(root, cfg):
    """Create and return the state directory (see ARCHITECTURE.md section 4)."""
    path = cfg_path(root, cfg, "gates", "state_dir")
    os.makedirs(path, exist_ok=True)
    return path


def state_file(root, cfg, name):
    return os.path.join(ensure_state_dir(root, cfg), name)


def use_utf8_stdout():
    """Windows consoles default to a legacy codepage; force UTF-8 when possible."""
    for stream in ("stdout", "stderr", "stdin"):
        try:
            getattr(__import__("sys"), stream).reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass
