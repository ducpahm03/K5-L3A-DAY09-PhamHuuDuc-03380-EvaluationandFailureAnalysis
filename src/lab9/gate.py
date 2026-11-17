"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, load_spec, per_item
from lab9.graders import GRADERS


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    problems: list[str] = []

    # 1. NaN or inf in pr["metrics"]
    for m, v in (pr.get("metrics") or {}).items():
        if isinstance(v, (int, float)) and (math.isnan(v) or math.isinf(v)):
            problems.append(f"metric {m} is {v}")

    # 2. Row count matches manifest items x len(manifest seeds)
    manifest = pr.get("manifest", {})
    expected_rows = manifest.get("items", 0) * len(manifest.get("seeds") or [])
    if len(pr.get("rows") or []) != expected_rows:
        problems.append(f"row count {len(pr.get('rows') or [])} != manifest items ({manifest.get('items')}) x seeds ({len(manifest.get('seeds') or [])})")

    # 3. (item_id, seed) set differs from baseline
    pr_pairs = {(r.get("item_id"), r.get("seed")) for r in pr.get("rows") or []}
    base_pairs = {(r.get("item_id"), r.get("seed")) for r in base.get("rows") or []}
    if pr_pairs != base_pairs:
        problems.append("PR (item_id, seed) set differs from baseline")

    # 4. evaluator_failures non-empty, or a row with None for a graded metric
    if pr.get("evaluator_failures"):
        problems.append(f"evaluator_failures non-empty: {pr['evaluator_failures']}")
    graded_ids = [m["id"] for m in spec.get("metrics", []) if m["id"] in GRADERS]
    for r in pr.get("rows") or []:
        for mid in graded_ids:
            if r.get(mid) is None:
                problems.append(f"row {r.get('item_id')}@{r.get('seed')} has None for graded metric {mid}")
                break
        if len(problems) > 10:
            break

    # 5. Ratchet check against base_spec
    if base_spec:
        if spec.get("eval_set_version") == base_spec.get("eval_set_version"):
            b_metrics = {m["id"]: m for m in base_spec.get("metrics", [])}
            p_metrics = {m["id"]: m for m in spec.get("metrics", [])}
            for mid, bm in b_metrics.items():
                if mid not in p_metrics:
                    problems.append(f"metric {mid} missing from spec (ratchet)")
                    continue
                pm = p_metrics[mid]
                if bm.get("blocking") and not pm.get("blocking"):
                    problems.append(f"metric {mid} demoted from blocking (ratchet)")
                b_th = bm.get("threshold", {})
                p_th = pm.get("threshold", {})
                if "min" in b_th and ("min" not in p_th or p_th["min"] < b_th["min"]):
                    problems.append(f"metric {mid} min lowered from {b_th.get('min')} to {p_th.get('min')} (ratchet)")
                if "max" in b_th and ("max" not in p_th or p_th["max"] > b_th["max"]):
                    problems.append(f"metric {mid} max raised from {b_th.get('max')} to {p_th.get('max')} (ratchet)")
                if "max_increase" in b_th and ("max_increase" not in p_th or p_th["max_increase"] > b_th["max_increase"]):
                    problems.append(f"metric {mid} max_increase loosened (ratchet)")
                if b_th.get("no_significant_drop") and not p_th.get("no_significant_drop"):
                    problems.append(f"metric {mid} dropped no_significant_drop (ratchet)")

            b_slices = {s["name"]: s for s in base_spec.get("slices", [])}
            p_slices = {s["name"]: s for s in spec.get("slices", [])}
            for sname, bs in b_slices.items():
                if sname not in p_slices:
                    problems.append(f"slice {sname} missing from spec (ratchet)")
                    continue
                ps = p_slices[sname]
                if bs.get("blocking") and not ps.get("blocking"):
                    problems.append(f"slice {sname} demoted from blocking (ratchet)")
                if "min" in bs and ("min" not in ps or ps["min"] < bs["min"]):
                    problems.append(f"slice {sname} min lowered (ratchet)")
                if bs.get("no_significant_drop") and not ps.get("no_significant_drop"):
                    problems.append(f"slice {sname} dropped no_significant_drop (ratchet)")

    # 6. Item slice tags altered
    pr_slices_map = {r.get("item_id"): tuple(sorted(r.get("slices") or [])) for r in pr.get("rows") or []}
    base_slices_map = {r.get("item_id"): tuple(sorted(r.get("slices") or [])) for r in base.get("rows") or []}
    for it_id, b_sl in base_slices_map.items():
        if it_id in pr_slices_map and pr_slices_map[it_id] != b_sl:
            problems.append(f"item {it_id} slice tags changed from {b_sl} to {pr_slices_map[it_id]}")
            break

    return problems


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked: list[str] = []
    lines: list[str] = []
    bs = spec.get("bootstrap", {})

    for sl in spec.get("slices", []):
        name = sl["name"]
        metric = sl["metric"]
        blocking = sl.get("blocking", True)
        pr_items = per_item(pr, metric, slice_name=name)
        base_items = per_item(base, metric, slice_name=name)

        if not pr_items:
            val = 0.0
        else:
            val = sum(pr_items.values()) / len(pr_items)

        verdict = "ok"
        note = ""
        if "min" in sl and val < sl["min"]:
            verdict = "fail"
        if sl.get("no_significant_drop") and pr_items:
            keys = sorted(set(pr_items) & set(base_items))
            if keys:
                d, lo, hi = stats.paired_bootstrap(
                    [pr_items[k] for k in keys],
                    [base_items[k] for k in keys],
                    n_resamples=bs.get("n_resamples", 1000),
                    rng=bs.get("rng", 2027),
                )
                note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                if hi < 0:
                    verdict = "fail"

        slice_id = f"slice:{name}/{metric}"
        if verdict != "ok" and blocking:
            blocked.append(slice_id)
        label = "BLOCK" if (verdict != "ok" and blocking) else ("warn" if verdict != "ok" else "ok")
        meta = {k: v for k, v in sl.items() if k not in ("name", "metric")}
        lines.append(f"  {slice_id:<22} {val:<8.4f} {json.dumps(meta):<40} {note:<28} {label}")

    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
