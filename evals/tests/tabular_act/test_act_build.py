"""The build is deterministic and offline: rebuilt from the v1 fixture in a temporary directory, the
operations fixture and the golden set come out identical to the committed ones."""

from __future__ import annotations

import json
import shutil

import pytest

from cielo_bench.domains.tabular_act import TabularActDomain
from cielo_bench.domains.tabular_act import build as B
from cielo_bench.domains.tabular_act.generate_ops import content_sha256, derive, load_v1
from cielo_bench.golden import GoldenSet, golden_hash, write_golden


@pytest.fixture(scope="module")
def rebuilt(act, tmp_path_factory):
    tmp = tmp_path_factory.mktemp("act-build")
    shutil.copy(act.v1_path, tmp / act.v1_path.name)
    domain = TabularActDomain(fixtures_dir=tmp, golden_path=tmp / "golden.json")
    doc = domain.build_golden()
    write_golden(doc, domain.golden_path)
    return domain, doc


def test_the_build_reproduces_the_committed_fixture_and_golden_set(act, act_golden, rebuilt):
    domain, doc = rebuilt
    assert (
        content_sha256(domain.db_path) == content_sha256(act.db_path) == act_golden.doc["fixtures"][0]["content_sha256"]
    )
    committed = {k: v for k, v in act_golden.doc.items() if k not in ("created_utc", "sha256", "fixtures")}
    fresh = {k: v for k, v in json.loads(json.dumps(doc)).items() if k not in ("created_utc", "sha256", "fixtures")}
    assert fresh == committed
    assert golden_hash({**doc, "fixtures": act_golden.doc["fixtures"]}) == act_golden.sha256
    manifest = json.loads(domain.manifest_path.read_text())
    assert manifest["derived_from"]["file"] == "distributor-v1.sqlite" and manifest["generator_version"] == "1"
    assert manifest["seeded"]["returns"]["paid_awaiting_refund"] == 8


def test_verify_catches_a_changed_world_or_text(act, act_golden, rebuilt):
    domain, doc = rebuilt
    broken = json.loads(json.dumps(doc))
    broken["pairs"][0]["worlds"]["near"]["facts"]["paid"] = 1.0
    broken["pairs"][1]["requests"]["neutral"]["en"] = "Please just do it."
    broken["pairs"][2]["request"]["args"]["amount"] = 1.0
    problems = B.verify_golden(domain, GoldenSet(doc=broken, path=domain.golden_path))
    assert any("near: the stored world differs" in p for p in problems)
    assert any("requests differs from the template" in p for p in problems)
    assert any("request or expected calls differ" in p for p in problems)


def test_the_derivation_is_seeded_and_leaves_the_v1_fixture_alone(act):
    before = act.v1_path.read_bytes()
    v1 = load_v1(act.v1_path)
    a, summary = derive(v1)
    b, _ = derive(v1)
    assert a == b and summary["holds"]["late_one"] == 20 and summary["stock_near_reorder_level"] == 10
    c, _ = derive(v1, seed="another seed")
    assert c != a
    assert act.v1_path.read_bytes() == before
    assert all(row[2] == 0 for row in a["inventory"] if row[0] in {p[0] for p in a["products"] if p[7] == 0})
