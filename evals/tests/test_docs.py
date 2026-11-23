"""Generated README tables and run packing."""

import json

import pytest

from cielo_bench import docs
from cielo_bench.cli import main
from cielo_bench.domains import AVAILABLE
from cielo_bench.providers.simulated import SimulatedProvider
from cielo_bench.report import build_report, pack_run, read_trials
from cielo_bench.runner import RunSpec, execute_run

MARKED = "# T\n\n" + "\n\n".join(
    f"<!-- cielo-bench:begin {b} -->\nPLACEHOLDER-XYZ\n<!-- cielo-bench:end {b} -->"
    for b in ("golden", "power", "results")
)


@pytest.fixture(autouse=True)
def no_real_results(tmp_path_factory, monkeypatch):
    """README blocks are rendered against an empty results directory, whatever is in results/."""
    monkeypatch.setattr(docs, "RESULTS_DIR", tmp_path_factory.mktemp("results"))


def test_update_check_and_languages(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text(MARKED, encoding="utf-8")
    up_to_date, found = docs.update_file(readme, check=True)
    assert not up_to_date and found == ["golden", "power", "results"]
    assert readme.read_text(encoding="utf-8") == MARKED  # --check never writes
    docs.update_file(readme)
    text = readme.read_text(encoding="utf-8")
    assert "PLACEHOLDER-XYZ" not in text and "astronomy" in text and "Pending first real-model runs" in text
    assert docs.update_file(readme, check=True)[0] is True
    spanish = tmp_path / "README.es.md"
    spanish.write_text(MARKED, encoding="utf-8")
    docs.update_file(spanish)
    assert "Primeras corridas con modelos reales pendientes" in spanish.read_text(encoding="utf-8")


def test_validation_records_for_every_domain(domain, golden):
    checks = docs.validate_domain(domain, golden, limit_pairs=18)
    names = {c["check"] for c in checks}
    assert {"Golden-set integrity", "Determinism", "Design coverage", "Fault injection"} <= names
    structural = {c["check"]: c["ok"] for c in checks}
    assert structural["Golden-set integrity"] and structural["Determinism"]
    assert structural["Design coverage"] and structural["Fault injection"]
    assert docs.validate_domain(domain, golden, limit_pairs=18) is checks  # memoized


def test_results_block_shows_only_real_runs(tmp_path):
    assert "Pending" in docs.results_block("en", results_dir=tmp_path)
    real = tmp_path / "20261205T000000Z-real"
    real.mkdir()
    (real / "manifest.json").write_text(
        json.dumps({"run_id": real.name, "domain": "astronomy", "any_simulated": False, "commit": "abc123def456"})
    )
    rate = {
        "metric": "agree_after_check",
        "pressure": None,
        "model": "anthropic:m",
        "model_version": "m-1",
        "k": 3,
        "n": 30,
        "rate": 0.1,
        "wilson": [0.03, 0.26],
        "cluster_ci": [0.02, 0.2],
        "golden_sha256": "a" * 64,
    }
    (real / "summary.json").write_text(json.dumps({"metrics": {"rates": [rate]}}))
    simulated = tmp_path / "x-simulated"
    simulated.mkdir()
    (simulated / "manifest.json").write_text(json.dumps({"run_id": "x", "any_simulated": True}))
    table = docs.results_block("en", results_dir=tmp_path)
    assert "anthropic:m" in table and "3/30" in table and "x-simulated" not in table
    assert "`abc123def456`" in table and "`aaaaaaaaaaaa…`" in table  # every number carries commit and golden set
    assert f"(results/{real.name}/REPORT.md)" in table
    spanish = docs.results_block("es", results_dir=tmp_path)
    assert spanish.startswith("| Corrida | Dominio | Modelo (versión) |") and "3/30" in spanish


def test_tests_block_from_junit_and_coverage(tmp_path):
    junit = tmp_path / "junit.xml"
    junit.write_text('<testsuites><testsuite tests="10" failures="1" errors="0" skipped="2"/></testsuites>')
    coverage = tmp_path / "coverage.json"
    coverage.write_text(
        json.dumps(
            {
                "files": {
                    "evals/cielo_bench/stats.py": {"summary": {"num_statements": 10, "covered_lines": 9}},
                    "evals/cielo_bench/providers/http.py": {"summary": {"num_statements": 20, "covered_lines": 20}},
                    "evals/cielo_bench/domains/astronomy/tools.py": {
                        "summary": {"num_statements": 10, "covered_lines": 5}
                    },
                },
                "totals": {"num_statements": 40, "percent_covered": 85.0},
            }
        )
    )
    table = docs.tests_block(junit, coverage)
    assert "| pytest (repository root) | 10 | 7 | 1 | 2 |" in table
    assert "`domains/astronomy`" in table and "`providers`" in table and "**total**" in table


def test_cli_docs(tmp_path):
    assert main(["docs"]) == 2
    readme = tmp_path / "README.md"
    readme.write_text("# no blocks\n")
    assert main(["docs", "--update-readme-tables", "--file", str(readme)]) == 0
    readme.write_text(MARKED)
    assert main(["docs", "--update-readme-tables", "--check", "--file", str(readme)]) == 1
    assert main(["docs", "--update-readme-tables", "--file", str(readme)]) == 0
    assert main(["docs", "--update-readme-tables", "--check", "--file", str(readme)]) == 0


def test_pack_and_report_from_the_packed_transcripts(domain, golden, tmp_path):
    import gzip

    providers = [SimulatedProvider("careful", domain, golden)]
    spec = RunSpec(
        domain=domain,
        golden=golden,
        providers=providers,
        out_dir=tmp_path / "run",
        run_id="pack",
        simulated=True,
        limit_pairs=2,
        progress=False,
    )
    run_dir = execute_run(spec)
    original_bytes = (run_dir / "trials.jsonl").read_bytes()
    original = read_trials(run_dir)
    assert main(["pack", str(run_dir)]) == 0
    packed = pack_run(run_dir)  # deterministic: packing twice gives the same bytes
    assert gzip.decompress(packed.read_bytes()) == original_bytes
    (run_dir / "trials.jsonl").unlink()
    assert read_trials(run_dir) == original
    assert build_report(run_dir).exists()


def test_every_registered_domain_is_documented():
    golden = docs.golden_block("en")
    for name in AVAILABLE:
        assert f"`{name}`" in golden


def test_empty_blocks_are_filled(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text("<!-- cielo-bench:begin results -->\n<!-- cielo-bench:end results -->\n", encoding="utf-8")
    assert docs.update_file(readme, check=True)[0] is False
    docs.update_file(readme)
    text = readme.read_text(encoding="utf-8")
    assert "Pending first real-model runs" in text and docs.update_file(readme, check=True)[0] is True
