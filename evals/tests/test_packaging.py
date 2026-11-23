"""The installed package: the wheel ships the golden sets and fixtures, and the code finds them.

From a checkout, ``cielo_bench`` reads ``evals/golden`` and ``evals/fixtures``. A wheel carries the
same files in ``cielo_bench/_data`` (``pyproject.toml`` maps them there at build time), and run
manifests name them as the repository does in both layouts. The first tests check that resolution
with a simulated installed layout. The last ones build the real sdist, then the wheel from it, and
run the installed code outside the repository, offline.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path

import pytest

from cielo_bench import __version__, config, report
from cielo_bench.domains import AVAILABLE, get_domain
from cielo_bench.domains.tabular import TabularDomain
from cielo_bench.golden import load_golden
from cielo_bench.providers.simulated import SimulatedProvider
from cielo_bench.runner import RunSpec, execute_run, relative

REPO = Path(__file__).resolve().parents[2]
EVALS = REPO / "evals"
ASTRONOMY_GOLDEN = "evals/golden/astronomy-v1/golden.json"
TABULAR_DB = "evals/fixtures/tabular/distributor-v1.sqlite"
# every golden set and fixture, named as in the repository (evals/<kind>/...)
DATA_FILES = sorted(
    p.relative_to(REPO).as_posix()
    for kind in config.DATA_KINDS
    for p in (EVALS / kind).rglob("*")
    if p.is_file() and not p.name.startswith(".")
)


def _pyproject(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


# ----------------------------------------------------------------------------- resolution
def test_a_checkout_reads_the_repository_data():
    assert not config.INSTALLED
    assert config.PROJECT_ROOT == config.CODE_ROOT == REPO
    assert config.GOLDEN_DIR == EVALS / "golden" and config.FIXTURES_DIR == EVALS / "fixtures"
    assert config.data_path(ASTRONOMY_GOLDEN) == REPO / ASTRONOMY_GOLDEN
    assert config.data_relpath(REPO / ASTRONOMY_GOLDEN) is None  # named relative to the project instead
    assert relative(REPO / ASTRONOMY_GOLDEN) == ASTRONOMY_GOLDEN
    assert TabularDomain().db_relpath == TABULAR_DB


def test_a_wheel_is_recognised_by_its_data_directory(tmp_path):
    package = tmp_path / "cielo_bench"
    package.mkdir()
    assert not config.is_installed(package)
    (package / "_data").mkdir()
    assert config.is_installed(package)


def test_git_commit_is_not_read_from_the_working_directory_when_installed():
    assert config.git_commit(None) == config.NO_COMMIT


@pytest.fixture
def installed(tmp_path, monkeypatch):
    """The installed layout: data in site-packages/cielo_bench/_data, the project in the working dir."""
    data = tmp_path / "site-packages" / "cielo_bench" / "_data"
    golden = data / "golden" / "astronomy-v1" / "golden.json"
    golden.parent.mkdir(parents=True)
    shutil.copyfile(REPO / ASTRONOMY_GOLDEN, golden)
    project = tmp_path / "work"
    project.mkdir()
    monkeypatch.setattr(config, "PACKAGED_DATA_DIR", data)
    monkeypatch.setattr(config, "DATA_DIR", data)
    monkeypatch.setattr(config, "PROJECT_ROOT", project)
    return data, project


def test_installed_paths_resolve_to_the_packaged_copy(installed):
    data, project = installed
    assert config.data_path(ASTRONOMY_GOLDEN) == data / "golden" / "astronomy-v1" / "golden.json"
    assert config.data_path(TABULAR_DB) == data / "fixtures" / "tabular" / "distributor-v1.sqlite"
    # anything else is relative to the project (the working directory)
    assert config.data_path("results/run/manifest.json") == project / "results" / "run" / "manifest.json"
    assert config.data_path("evals/runs/x/manifest.json") == project / "evals" / "runs" / "x" / "manifest.json"
    # and packaged files are named as the repository names them
    assert config.data_relpath(data / "golden" / "astronomy-v1" / "golden.json") == ASTRONOMY_GOLDEN
    assert config.data_relpath(data / "fixtures" / "tabular" / "distributor-v1.sqlite") == TABULAR_DB
    assert config.data_relpath(data / "other.txt") is None
    assert config.data_relpath(project / "results" / "x") is None
    assert TabularDomain(fixtures_dir=data / "fixtures" / "tabular").db_relpath == TABULAR_DB


def test_a_run_from_the_installed_layout_records_and_reloads_the_repository_path(installed, tmp_path):
    data, _ = installed
    domain = get_domain("astronomy")
    golden = load_golden(data / "golden" / "astronomy-v1" / "golden.json")
    run_dir = execute_run(
        RunSpec(
            domain=domain,
            golden=golden,
            providers=[SimulatedProvider("careful", domain, golden)],
            out_dir=tmp_path / "run",
            run_id="installed-layout",
            simulated=True,
            progress=False,
            limit_pairs=1,
            conditions=("tool",),
        )
    )
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["golden"]["path"] == ASTRONOMY_GOLDEN  # the same record as from a checkout
    _, scored, reloaded = report.score_run(run_dir)
    assert reloaded.path == data / "golden" / "astronomy-v1" / "golden.json"
    assert reloaded.sha256 == load_golden(REPO / ASTRONOMY_GOLDEN).sha256 and scored


# ----------------------------------------------------------------------------- build configuration
def test_the_build_lists_every_code_package_and_maps_the_data():
    setuptools = _pyproject(REPO / "pyproject.toml")["tool"]["setuptools"]
    code = {
        ".".join(p.parent.relative_to(EVALS).parts)
        for p in (EVALS / "cielo_bench").rglob("__init__.py")
        if "__pycache__" not in p.parts
    }
    data = {f"cielo_bench._data.{kind}" for kind in config.DATA_KINDS}
    assert set(setuptools["packages"]) == code | data
    assert setuptools["package-dir"] == {
        "": "evals",
        **{f"cielo_bench._data.{k}": f"evals/{k}" for k in config.DATA_KINDS},
    }


# ----------------------------------------------------------------------------- the real wheel
def _build(source: Path, hook: str, out: Path) -> Path:
    """Call the build backend in a subprocess, without isolation (no network): sdist or wheel."""
    out.mkdir(parents=True, exist_ok=True)
    code = f"import sys, setuptools.build_meta as b; print(b.{hook}(sys.argv[1]))"
    done = subprocess.run(
        [sys.executable, "-c", code, str(out)], cwd=source, capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stderr[-2000:]
    return out / done.stdout.strip().splitlines()[-1]


@pytest.fixture(scope="module")
def wheel(tmp_path_factory) -> Path:
    """The wheel as a release builds it: the sdist first, then the wheel from the unpacked sdist."""
    setuptools = pytest.importorskip("setuptools", reason="building the wheel needs setuptools (the dev extra)")
    if int(setuptools.__version__.split(".")[0]) < 77:
        pytest.skip("pyproject.toml requires setuptools>=77")
    tmp = tmp_path_factory.mktemp("build")
    source = tmp / "source"
    source.mkdir()
    project = _pyproject(REPO / "pyproject.toml")["project"]
    readme = project["readme"] if isinstance(project["readme"], str) else project["readme"]["file"]
    for name in ("pyproject.toml", readme, *project["license-files"]):
        shutil.copyfile(REPO / name, source / name)
    ignore = shutil.ignore_patterns("__pycache__", "*.egg-info")
    for name in ("cielo_bench", *config.DATA_KINDS):
        shutil.copytree(EVALS / name, source / "evals" / name, ignore=ignore)
    sdist = _build(source, "build_sdist", tmp / "sdist")
    with tarfile.open(sdist) as archive:
        archive.extractall(tmp / "unpacked", filter="data")
    (unpacked,) = (tmp / "unpacked").iterdir()
    return _build(unpacked, "build_wheel", tmp / "wheel")


def test_the_wheel_ships_every_golden_set_and_fixture_byte_for_byte(wheel):
    with zipfile.ZipFile(wheel) as archive:
        shipped = {
            "evals/" + name.removeprefix("cielo_bench/_data/"): archive.read(name)
            for name in archive.namelist()
            if name.startswith("cielo_bench/_data/")
        }
    assert sorted(shipped) == DATA_FILES
    assert all(shipped[name] == (REPO / name).read_bytes() for name in DATA_FILES)


def test_the_installed_wheel_runs_offline_outside_the_repository(wheel, tmp_path):
    site, work = tmp_path / "site-packages", tmp_path / "work"
    work.mkdir()
    with zipfile.ZipFile(wheel) as archive:
        archive.extractall(site)
    before = sorted(p.relative_to(site) for p in site.rglob("*"))
    env = {k: v for k, v in os.environ.items() if not k.startswith("CIELO_")}
    env.update(PYTHONPATH=str(site), MPLBACKEND="Agg", CIELO_CACHE_DIR=str(tmp_path / "live-cache"))

    def cli(*args: str) -> str:
        done = subprocess.run(
            [sys.executable, "-m", "cielo_bench", *args], cwd=work, env=env, capture_output=True, text=True, check=False
        )
        assert done.returncode == 0, done.stdout[-2000:] + done.stderr[-2000:]
        return done.stdout

    where = subprocess.run(
        [sys.executable, "-c", "import cielo_bench.config as c; print(c.INSTALLED, c.GOLDEN_DIR)"],
        cwd=work,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    assert where[0] == "True" and Path(where[1]) == site / "cielo_bench" / "_data" / "golden"

    for name in AVAILABLE:
        expected = load_golden(get_domain(name).golden_path).sha256  # the repository's golden set
        assert f"sha256 {expected}" in cli("--domain", name, "verify")

    cli("run", "--simulated", "--limit", "1", "--workers", "1")
    (run_dir,) = (work / "results").iterdir()  # results go to the working directory
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["golden"]["path"] == ASTRONOMY_GOLDEN and manifest["commit"] == config.NO_COMMIT
    assert manifest["code_version"] == __version__ and (run_dir / "REPORT.md").is_file()
    assert sorted(p.relative_to(site) for p in site.rglob("*") if "__pycache__" not in p.parts) == [
        p for p in before if "__pycache__" not in p.parts
    ]  # the installed data is read, never written
