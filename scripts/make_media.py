"""Render README charts and app screenshots.

Requires the dev extras (pip install -r requirements-dev.txt, then
`python -m playwright install chromium`) and a running app:

    streamlit run app.py --server.headless true --server.port 8502
    python scripts/make_media.py --url http://localhost:8502
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright  # noqa: E402

from scripts.export_workbook import LSL, USL, load  # noqa: E402
from stackup import pfmea, stack  # noqa: E402
from stackup.plots import contribution_figure, gap_figure, rpn_pareto  # noqa: E402

CHARTS = ROOT / "docs" / "charts"
MEDIA = ROOT / "docs" / "media"
PAGES = {"02_app_stackup.png": "📏 Stack-up", "03_app_pfmea.png": "⚠️ PFMEA",
         "04_app_traceability.png": "🔗 Traceability & export"}


def build_figures():
    dims, modes, _ = load()
    r = stack.analyze(dims, LSL, USL)
    mc = stack.monte_carlo(dims, LSL, USL)
    return {"gap_distribution.png": gap_figure(r, mc), "contributions.png": contribution_figure(r),
            "rpn_pareto.png": rpn_pareto(pfmea.ranked(modes))}


def render_charts(page):
    CHARTS.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        for name, fig in build_figures().items():
            fig.update_layout(width=1200, height=560)
            html = Path(tmp) / "fig.html"
            fig.write_html(html, include_plotlyjs="cdn", full_html=True)
            page.set_viewport_size({"width": 1200, "height": 560})
            page.goto(html.as_uri())
            page.wait_for_selector(".main-svg")
            page.wait_for_timeout(500)
            page.screenshot(path=str(CHARTS / name))
            print("chart", name)


def render_app(page, url: str):
    MEDIA.mkdir(parents=True, exist_ok=True)
    page.set_viewport_size({"width": 1600, "height": 1000})
    for name, label in PAGES.items():
        page.goto(url)
        page.wait_for_selector("section[data-testid='stSidebar']", timeout=60_000)
        page.get_by_text(label, exact=True).click()
        page.wait_for_timeout(3500)
        page.screenshot(path=str(MEDIA / name), full_page=False)
        print("screenshot", name)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", help="running app URL; omit to render charts only")
    args = ap.parse_args()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(device_scale_factor=1.5)
        render_charts(page)
        if args.url:
            render_app(page, args.url)
        browser.close()
