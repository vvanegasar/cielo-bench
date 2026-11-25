"""Agreement with the user's numeric claim as a function of its exact distance from the tool's value.

Uses the versioned runs only (no API, no network): tool condition, numeric templates, trials where the
tool returned evidence. The response is VERDICT: TRUE. The bins are post hoc and trials are not
independent (items repeat across pressures), so read the rates as a map of where to look, not as estimates.

    python scripts/distance_curve.py
"""

from __future__ import annotations

import glob
import json
import os

from cielo_bench.scoring import premise_number

BINS = {
    "angle_deg": ([0, 2, 5, 10, 20, 40, 400], "deg"),
    "number": ([0, 2, 5, 10, 20, 50, 400], "pp"),
    "clock_time": ([0, 3, 10, 25, 60, 200, 2000], "min"),
}


def collect() -> list[tuple[str, str, float, bool, str]]:
    rows = []
    for run in sorted(glob.glob("results/2026-11-2*-astronomy*")):
        manifest_path, scores_path = f"{run}/manifest.json", f"{run}/scores.jsonl"
        if not (os.path.exists(manifest_path) and os.path.exists(scores_path)):
            continue
        manifest = json.load(open(manifest_path, encoding="utf-8"))
        if manifest.get("any_simulated"):
            continue
        pairs = {p["pair_id"]: p for p in json.load(open(manifest["golden"]["path"], encoding="utf-8"))["pairs"]}
        for line in open(scores_path, encoding="utf-8"):
            s = json.loads(line)
            if s["condition"] != "tool" or s["excluded"] or not s.get("value_kind") or not s.get("obtained_evidence"):
                continue
            claimed = premise_number(pairs[s["pair_id"]], s["premise"])
            if claimed is None:
                continue
            distance = abs(claimed - s["value_target"])
            if s["value_kind"] == "clock_time":
                distance = min(distance, 1440 - distance)
            rows.append((s["model"], s["value_kind"], distance, s["verdict"] == "TRUE", s["pair_id"]))
    return rows


def main() -> None:
    rows = collect()
    print(f"{len(rows)} tool trials with a numeric premise")
    for model in sorted({r[0] for r in rows}):
        print(f"\n{model}")
        for kind, (edges, unit) in BINS.items():
            cells = []
            for lo, hi in zip(edges, edges[1:], strict=False):
                sel = [r for r in rows if r[0] == model and r[1] == kind and lo <= r[2] < hi]
                if sel:
                    items = len({r[4] for r in sel})
                    cells.append(f"[{lo},{hi}){unit}: {sum(r[3] for r in sel)}/{len(sel)} ({items} items)")
            if cells:
                print(f"  {kind}: " + " | ".join(cells))


if __name__ == "__main__":
    main()
