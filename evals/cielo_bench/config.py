"""Paths, local settings and run metadata shared by every domain."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping
from pathlib import Path

from . import __version__

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EVALS_DIR = PROJECT_ROOT / "evals"
GOLDEN_DIR = EVALS_DIR / "golden"
FIXTURES_DIR = EVALS_DIR / "fixtures"
DRY_RUNS_DIR = EVALS_DIR / "runs"  # git-ignored scratch runs (dry runs)
RESULTS_DIR = PROJECT_ROOT / "results"
RUNS_DIR = RESULTS_DIR / "runs"  # real runs: raw outputs meant to be committed
ENV_FILE = PROJECT_ROOT / ".env"

ENV_PREFIX = "CIELO_"
DEFAULT_USER_AGENT = f"cielo-bench/{__version__} (non-commercial research benchmark)"
NO_COMMIT = "no-commit"


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse a minimal KEY=VALUE file. Blank lines and # comments are ignored."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        values[key] = value
    return values


def load_settings(env_file: Path | None = None, environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return project settings: the project's .env file, overridden by CIELO_* variables.

    Only names that start with ``CIELO_`` are read, from either source. Generic provider
    variables such as ``ANTHROPIC_API_KEY`` or ``OPENAI_API_KEY`` are ignored on purpose:
    they may hold a key from another account (for example an employer's), and this
    project must only ever run on personal keys.
    """
    env_file = ENV_FILE if env_file is None else env_file
    environ = os.environ if environ is None else environ
    settings = {k: v for k, v in parse_env_file(env_file).items() if k.startswith(ENV_PREFIX)}
    settings.update({k: v for k, v in environ.items() if k.startswith(ENV_PREFIX)})
    return settings


def live_cache_dir(settings: Mapping[str, str] | None = None) -> Path:
    """Where live upstream responses are cached: never inside the repository's fixtures.

    ``CIELO_CACHE_DIR`` (settings, then environment), else ``$XDG_CACHE_HOME/cielo-bench``,
    else ``~/.cache/cielo-bench``.
    """
    configured = (settings or {}).get("CIELO_CACHE_DIR") or os.environ.get("CIELO_CACHE_DIR")
    if configured:
        return Path(configured).expanduser()
    base = os.environ.get("XDG_CACHE_HOME")
    return (Path(base) if base else Path.home() / ".cache") / "cielo-bench"


def user_agent(settings: Mapping[str, str] | None = None) -> str:
    """User-Agent sent to upstream sources. Generic on purpose: no personal data."""
    if settings and settings.get("CIELO_USER_AGENT"):
        return settings["CIELO_USER_AGENT"]
    return DEFAULT_USER_AGENT


def git_commit(root: Path = PROJECT_ROOT) -> str:
    """Short commit of the project repo, with -dirty if there are local changes.

    Returns ``no-commit`` when the project is not (yet) its own git repository.
    """
    try:
        top = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if top.returncode != 0 or Path(top.stdout.strip()).resolve() != root.resolve():
            return NO_COMMIT
        head = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if head.returncode != 0:
            return NO_COMMIT
        status = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        dirty = "-dirty" if status.stdout.strip() else ""
        return head.stdout.strip()[:12] + dirty
    except (OSError, subprocess.SubprocessError):
        return NO_COMMIT
