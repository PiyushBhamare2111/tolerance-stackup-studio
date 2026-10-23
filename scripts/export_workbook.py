"""Build docs/end_play_stackup.xlsx from the bundled sample data.

With --verify (Windows + Excel only), the workbook is opened in Excel, fully
recalculated, and every formula result is compared with the Python library.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from stackup import controlplan, pfmea, stack  # noqa: E402
from stackup.excel import build_workbook  # noqa: E402

LSL, USL, MC_N = 0.10, 0.60, 200_000
OUT = ROOT / "docs" / "end_play_stackup.xlsx"


def load():
    dims = stack.from_frame(pd.read_csv(ROOT / "data" / "end_play_stack.csv"))
    modes = pfmea.from_frame(pd.read_csv(ROOT / "data" / "pfmea.csv", encoding="utf-8"))
    plan = controlplan.from_frame(pd.read_csv(ROOT / "data" / "control_plan.csv", encoding="utf-8"))
    return dims, modes, plan


def export(path: Path = OUT) -> Path:
    dims, modes, plan = load()
    mc = stack.monte_carlo(dims, LSL, USL, n=MC_N)
    findings = controlplan.check_pfmea_coverage(modes, plan) + controlplan.check_stack_assumptions(dims, plan)
    path.parent.mkdir(parents=True, exist_ok=True)
    build_workbook(dims, LSL, USL, mc, MC_N, modes, plan, findings).save(path)
    return path


def verify(path: Path) -> int:
    import win32com.client  # Windows only

    dims, modes, _ = load()
    r = stack.analyze(dims, LSL, USL)
    excel = win32com.client.DispatchEx("Excel.Application")
    excel.Visible = False
    try:
        wb = excel.Workbooks.Open(str(path), ReadOnly=True)
        excel.CalculateFull()
        ws = wb.Worksheets("Stack-up")
        s = 7 + len(dims) + 1
        got = {label: ws.Range(f"B{s + i}").Value for i, label in enumerate(
            ["nominal", "mean", "wc_half", "wc_min", "wc_max", "wc_verdict", "rss_half", "rss_min", "rss_max",
             "rss_verdict", "sigma", "cpk", "ppm"])}
        want = {"nominal": r.nominal_gap, "mean": r.mean_gap, "wc_half": r.wc_half, "wc_min": r.wc_limits[0],
                "wc_max": r.wc_limits[1], "wc_verdict": "PASS" if r.passes(r.wc_limits) else "FAIL",
                "rss_half": r.rss_half, "rss_min": r.rss_limits[0], "rss_max": r.rss_limits[1],
                "rss_verdict": "PASS" if r.passes(r.rss_limits) else "FAIL", "sigma": r.sigma_gap,
                "cpk": r.cpk, "ppm": r.ppm}
        p = wb.Worksheets("PFMEA")
        for i, m in enumerate(modes):
            got[f"rpn_{m.id}"], want[f"rpn_{m.id}"] = p.Range(f"L{5 + i}").Value, m.rpn
            got[f"prio_{m.id}"], want[f"prio_{m.id}"] = p.Range(f"M{5 + i}").Value, m.priority()
        wb.Close(SaveChanges=False)
    finally:
        excel.Quit()

    bad = 0
    for key, w in want.items():
        g = got[key]
        ok = g == w if isinstance(w, str) else abs(float(g) - w) <= 1e-9 * max(1.0, abs(w))
        bad += not ok
        print(f"{'ok ' if ok else 'BAD'} {key:12} excel={g!r:<24} python={w!r}")
    print(f"\n{len(want) - bad}/{len(want)} Excel formula results match the Python library")
    return 1 if bad else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true", help="recalculate in Excel and compare with Python")
    args = ap.parse_args()
    out = export()
    print(f"wrote {out}")
    sys.exit(verify(out) if args.verify else 0)
