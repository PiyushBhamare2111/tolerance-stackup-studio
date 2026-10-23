"""Control plan, plus the traceability checks that tie it to the PFMEA and the stack-up.

The three documents usually live in separate files owned by different people,
and they drift apart.  These checks catch the two gaps that matter most:

1. A high-risk or special-characteristic failure mode with no control.
2. A stack-up that only closes because it assumes Cp > 1 on some dimension,
   while the control plan does not require that capability (or does not
   control the dimension at all, or uses a different spec).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

from .pfmea import FailureMode
from .stack import Dimension

COLUMNS = ["step", "characteristic", "char_class", "lsl", "usl", "method", "sample_size", "frequency",
           "control_method", "required_cpk", "reaction_plan", "pfmea_id", "stack_dimension"]


@dataclass(frozen=True)
class ControlItem:
    step: str
    characteristic: str
    char_class: str
    lsl: float | None
    usl: float | None
    method: str
    sample_size: str
    frequency: str
    control_method: str
    required_cpk: float | None
    reaction_plan: str
    pfmea_id: str = ""            # comma-separated PFMEA ids this line controls
    stack_dimension: str = ""     # stack-up dimension name this line controls

    @property
    def pfmea_ids(self) -> set[str]:
        return {p.strip() for p in self.pfmea_id.split(",") if p.strip()}


@dataclass(frozen=True)
class Finding:
    level: str      # "error" or "warning"
    message: str


def _num(v):
    return None if v is None or (isinstance(v, float) and math.isnan(v)) or v == "" else float(v)


def from_frame(df: pd.DataFrame) -> list[ControlItem]:
    missing = {"step", "characteristic", "method", "frequency", "reaction_plan"} - set(df.columns)
    if missing:
        raise ValueError(f"missing columns: {sorted(missing)}")
    items = []
    for r in df.to_dict("records"):
        text = {c: ("" if r.get(c) is None or (isinstance(r.get(c), float) and math.isnan(r.get(c)))
                    else str(r.get(c))) for c in COLUMNS}
        items.append(ControlItem(**{**text, "lsl": _num(r.get("lsl")), "usl": _num(r.get("usl")),
                                    "required_cpk": _num(r.get("required_cpk"))}))
    return items


def to_frame(items: list[ControlItem]) -> pd.DataFrame:
    return pd.DataFrame([{c: getattr(i, c) for c in COLUMNS} for i in items])


def check_pfmea_coverage(modes: list[FailureMode], plan: list[ControlItem],
                         rpn_threshold: int = 100) -> list[Finding]:
    covered = set().union(*(i.pfmea_ids for i in plan)) if plan else set()
    known = {m.id for m in modes}
    findings = []
    for m in modes:
        needs = m.priority(rpn_threshold) != "Low" or m.special_char
        if needs and m.id not in covered:
            why = f"special characteristic {m.special_char}" if m.special_char else f"{m.priority(rpn_threshold)} priority"
            findings.append(Finding("error", f"PFMEA {m.id} ({m.failure_mode}) is {why} but no control plan line covers it"))
    for i in plan:
        for pid in i.pfmea_ids - known:
            findings.append(Finding("warning", f"Control plan line '{i.characteristic}' references unknown PFMEA id {pid}"))
    return findings


def check_stack_assumptions(dims: list[Dimension], plan: list[ControlItem], tol: float = 1e-9) -> list[Finding]:
    by_dim = {}
    for i in plan:
        if i.stack_dimension:
            by_dim.setdefault(i.stack_dimension, []).append(i)
    findings = []
    for d in dims:
        lines = by_dim.get(d.name, [])
        if not lines:
            level = "error" if d.cp > 1 else "warning"
            findings.append(Finding(level, f"Stack dimension '{d.name}' has no control plan line"
                                           + (f" but the stack-up assumes Cp {d.cp:g}" if d.cp > 1 else "")))
            continue
        lsl, usl = d.nominal + d.lower, d.nominal + d.upper
        for i in lines:
            if (i.lsl is not None and abs(i.lsl - lsl) > tol) or (i.usl is not None and abs(i.usl - usl) > tol):
                findings.append(Finding("error", f"'{d.name}': control plan spec {i.lsl}-{i.usl} "
                                                 f"does not match the stack-up {lsl:g}-{usl:g}"))
        if d.cp > 1:
            best = max((i.required_cpk or 0.0) for i in lines)
            if best + tol < d.cp:
                findings.append(Finding("error", f"'{d.name}': stack-up assumes Cp {d.cp:g} but the control plan "
                                                 f"only requires Cpk {best:g}"))
    for name in set(by_dim) - {d.name for d in dims}:
        findings.append(Finding("warning", f"Control plan references unknown stack dimension '{name}'"))
    return findings
