"""Plotly figures in the same dark theme as the other portfolio apps."""

from __future__ import annotations

import numpy as np
import plotly.graph_objects as go

from .stack import MonteCarloResult, StackResult

ORANGE, BLUE, RED, GREEN, GREY = "#ff8a3d", "#5b7fa8", "#e5534b", "#57ab5a", "#8b8f98"
LAYOUT = dict(template="plotly_dark", paper_bgcolor="#0b0c0f", plot_bgcolor="#14161b",
              font=dict(color="#e8e8ea"), margin=dict(l=50, r=20, t=50, b=40))


def gap_figure(r: StackResult, mc: MonteCarloResult) -> go.Figure:
    fig = go.Figure()
    fig.add_histogram(x=mc.samples, nbinsx=120, marker_color=BLUE, opacity=0.85, name="Monte Carlo gap")
    ymax = np.histogram(mc.samples, bins=120)[0].max()
    bands = [("Worst case", r.wc_limits, ORANGE, 1.18), ("RSS", r.rss_limits, GREEN, 1.08)]
    for label, (lo, hi), color, y in bands:
        fig.add_trace(go.Scatter(x=[lo, hi], y=[ymax * y] * 2, mode="lines+markers", name=f"{label} {lo:.3f}-{hi:.3f}",
                                 line=dict(color=color, width=4), marker=dict(symbol="line-ns-open", size=14)))
    for value, label in ((r.lsl, "LSL"), (r.usl, "USL")):
        if value is not None:
            fig.add_vline(x=value, line=dict(color=RED, dash="dash"), annotation_text=f"{label} {value:g}",
                          annotation_position="top")
    fig.update_layout(**LAYOUT, title="Gap distribution vs. worst-case and RSS limits", xaxis_title="Gap (mm)",
                      yaxis_title="Count", legend=dict(orientation="h", y=-0.2), bargap=0)
    return fig


def contribution_figure(r: StackResult) -> go.Figure:
    df = r.contributions.sort_values("stat_pct")
    fig = go.Figure()
    fig.add_bar(y=df["dimension"], x=df["wc_pct"], orientation="h", name="Worst case (t / Σt)", marker_color=ORANGE)
    fig.add_bar(y=df["dimension"], x=df["stat_pct"], orientation="h", name="Statistical (σ² / Σσ²)", marker_color=BLUE)
    fig.update_layout(**LAYOUT, barmode="group", title="Which tolerance drives the gap?", xaxis_title="% contribution",
                      legend=dict(orientation="h", y=-0.2))
    return fig


def rpn_pareto(df) -> go.Figure:
    colors = {"High": RED, "Medium": ORANGE, "Low": GREY}
    d = df.sort_values("rpn", ascending=False)
    fig = go.Figure(go.Bar(x=d["id"] + " " + d["failure_mode"].str.slice(0, 28), y=d["rpn"],
                           marker_color=[colors[p] for p in d["priority"]],
                           text=[f"S{s}" for s in d["severity"]], textposition="outside"))
    fig.update_layout(**LAYOUT, title="RPN Pareto (colour = priority; label = severity)", yaxis_title="RPN")
    return fig
