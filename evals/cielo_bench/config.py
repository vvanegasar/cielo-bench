"""Paths, local settings and run metadata shared by every domain.

The code runs in one of two layouts:

* **Checkout** (the repository, ``pip install -e .``, or ``pythonpath = evals``). The golden sets
  and fixtures are read where the repository keeps them, ``evals/golden`` and ``evals/fixtures``,
  and the project is the repository root.
* **Installed** from a wheel (``pip install cielo-bench``). The wheel carries the same files in
  ``cielo_bench/_data/{golden,fixtures}``: the build maps the repository's directories there
  (``pyproject.toml``, ``[tool.setuptools.package-dir]``), so nothing is moved or copied in the
  repository. The project is the working directory: ``results/`` and ``.env`` are looked up there.

Run manifests always record golden sets as the repository names them
(``evals/golden/astronomy-v1/golden.json``), whichever layout wrote them: ``data_path`` turns such a
path back into a file, and ``data_relpath`` names a packaged file the same way.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping
from pathlib import Path

from . import __version__

PACKAGE_DIR = Path(__file__).resolve().parent
PACKAGED_DATA_DIR = PACKAGE_DIR / "_data"  # only in a built wheel
DATA_KINDS = ("golden", "fixtures")  # the subdirectories of evals/ that a wheel ships


def is_installed(package_dir: Path = PACKAGE_DIR) -> bool:
    """True when the package runs from a built wheel, which carries its data in ``_data/``."""
    return (package_dir / "_data").is_dir()


def _working_dir() -> Path:
    try:
        return Path.cwd().resolve()
    except OSError:  # the working directory no longer exists
        return Path.home()


INSTALLED = is_installed()
PROJECT_ROOT = _working_dir() if INSTALLED else PACKAGE_DIR.parents[1]
CODE_ROOT: Path | None = None if INSTALLED else PROJECT_ROOT  # the git checkout the code runs from
EVALS_DIR = PROJECT_ROOT / "evals"
DATA_DIR = PACKAGED_DATA_DIR if INSTALLED else EVALS_DIR  # holds golden/ and fixtures/
GOLDEN_DIR = DATA_DIR / "golden"
FIXTURES_DIR = DATA_DIR / "fixtures"
DRY_RUNS_DIR = EVALS_DIR / "runs"  # git-ignored scratch runs (dry runs)
RESULTS_DIR = PROJECT_ROOT / "results"
RUNS_DIR = RESULTS_DIR / "runs"  # real runs: raw outputs meant to be committed
ENV_FILE = PROJECT_ROOT / ".env"

ENV_PREFIX = "CIELO_"
DEFAULT_USER_AGENT = f"cielo-bench/{__version__} (non-commercial research benchmark)"
NO_COMMIT = "no-commit"


def data_path(relpath: str | Path) -> Path:
    """The file behind a project-relative path as run manifests record it.

    ``evals/golden/…`` and ``evals/fixtures/…`` resolve to the data this code runs with: the
    repository's files in a checkout, the packaged copy when installed. Other paths are relative to
    the project.
    """
    rel = Path(relpath)
    parts = rel.parts
    if not rel.is_absolute() and len(parts) > 2 and parts[0] == "evals" and parts[1] in DATA_KINDS:
        return DATA_DIR.joinpath(*parts[1:])
    return PROJECT_ROOT / rel


def data_relpath(path: Path) -> str | None:
    """``evals/golden/…`` or ``evals/fixtures/…`` for a file inside the installed package's data,
    named as in the repository; None for any other path."""
    try:
        rel = Path(path).resolve().relative_to(PACKAGED_DATA_DIR)
    except ValueError:
        return None
    if not rel.parts or rel.parts[0] not in DATA_KINDS:
        return None
    return Path("evals", rel).as_posix()


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


def git_commit(root: Path | None = CODE_ROOT) -> str:
    """Short commit of the project repo, with -dirty if there are local changes.

    Returns ``no-commit`` when the project is not (yet) its own git repository, and when the code
    runs from an installed wheel (``code_version`` then identifies it), whatever the working
    directory is.
    """
    if root is None:
        return NO_COMMIT
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
