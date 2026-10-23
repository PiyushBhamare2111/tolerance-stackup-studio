"""Process FMEA: severity x occurrence x detection.

Ratings follow the AIAG FMEA 4th edition 1-10 scales, and RPN = S x O x D.
RPN is kept because most plants still report it, but it is not used alone:
two failure modes with the same RPN can carry very different risk (S=10,
O=2, D=5 vs S=4, O=5, D=5).  Severity 9-10 (safety or regulatory) always
needs action whatever the RPN.  This matches the guidance behind the
AIAG-VDA 2019 Action Priority table, which this module does not implement.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

RATING_COLUMNS = ("severity", "occurrence", "detection")
COLUMNS = ["id", "step", "function", "failure_mode", "effect", "severity", "cause", "occurrence",
           "prevention", "detection_control", "detection", "special_char", "action"]


@dataclass(frozen=True)
class FailureMode:
    id: str
    step: str
    function: str
    failure_mode: str
    effect: str
    severity: int
    cause: str
    occurrence: int
    prevention: str
    detection_control: str
    detection: int
    special_char: str = ""    # "CC" critical, "SC" significant, "" none
    action: str = ""

    def __post_init__(self):
        for col in RATING_COLUMNS:
            value = getattr(self, col)
            if not isinstance(value, int) or not 1 <= value <= 10:
                raise ValueError(f"{self.id}: {col} must be an integer 1-10, got {value!r}")
        if self.special_char not in ("", "CC", "SC"):
            raise ValueError(f"{self.id}: special_char must be '', 'CC' or 'SC'")

    @property
    def rpn(self) -> int:
        return self.severity * self.occurrence * self.detection

    def priority(self, rpn_threshold: int = 100) -> str:
        if self.severity >= 9:
            return "High"
        if self.rpn >= rpn_threshold or (self.severity >= 7 and self.occurrence >= 4):
            return "Medium"
        return "Low"


def from_frame(df: pd.DataFrame) -> list[FailureMode]:
    missing = set(COLUMNS) - {"special_char", "action"} - set(df.columns)
    if missing:
        raise ValueError(f"missing columns: {sorted(missing)}")
    rows = []
    for r in df.to_dict("records"):
        kw = {c: ("" if pd.isna(r.get(c)) else str(r.get(c))) for c in COLUMNS if c not in RATING_COLUMNS}
        kw.update({c: int(r[c]) for c in RATING_COLUMNS})
        rows.append(FailureMode(**kw))
    return rows


def to_frame(modes: list[FailureMode], rpn_threshold: int = 100) -> pd.DataFrame:
    df = pd.DataFrame([{c: getattr(m, c) for c in COLUMNS} for m in modes])
    df["rpn"] = [m.rpn for m in modes]
    df["priority"] = [m.priority(rpn_threshold) for m in modes]
    return df


def ranked(modes: list[FailureMode], rpn_threshold: int = 100) -> pd.DataFrame:
    """Highest risk first: priority band, then severity, then RPN."""
    order = {"High": 0, "Medium": 1, "Low": 2}
    df = to_frame(modes, rpn_threshold)
    return (df.assign(_p=df["priority"].map(order))
              .sort_values(["_p", "severity", "rpn"], ascending=[True, False, False])
              .drop(columns="_p").reset_index(drop=True))
