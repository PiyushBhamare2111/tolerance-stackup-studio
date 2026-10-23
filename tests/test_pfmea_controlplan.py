"""PFMEA scoring and the PFMEA <-> control plan <-> stack-up traceability checks."""

from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

from stackup import controlplan, pfmea, stack
from stackup.pfmea import FailureMode

DATA = Path(__file__).resolve().parents[1] / "data"


@pytest.fixture
def modes():
    return pfmea.from_frame(pd.read_csv(DATA / "pfmea.csv", encoding="utf-8"))


@pytest.fixture
def plan():
    return controlplan.from_frame(pd.read_csv(DATA / "control_plan.csv", encoding="utf-8"))


@pytest.fixture
def dims():
    return stack.from_frame(pd.read_csv(DATA / "end_play_stack.csv"))


def fm(**kw):
    base = dict(id="X", step="s", function="f", failure_mode="m", effect="e", severity=5, cause="c",
                occurrence=5, prevention="p", detection_control="d", detection=5)
    return FailureMode(**{**base, **kw})


# -------------------------------------------------------------------- PFMEA
def test_rpn_is_product():
    assert fm(severity=7, occurrence=4, detection=5).rpn == 140


@pytest.mark.parametrize("kw, expected", [
    (dict(severity=9, occurrence=1, detection=1), "High"),      # severity overrides a tiny RPN
    (dict(severity=10, occurrence=2, detection=2), "High"),
    (dict(severity=5, occurrence=5, detection=4), "Medium"),     # RPN 100 hits threshold
    (dict(severity=7, occurrence=4, detection=1), "Medium"),     # S>=7 with frequent occurrence
    (dict(severity=8, occurrence=3, detection=4), "Low"),        # RPN 96
])
def test_priority_rules(kw, expected):
    assert fm(**kw).priority(100) == expected


def test_threshold_is_configurable():
    assert fm(severity=5, occurrence=4, detection=4).priority(50) == "Medium"
    assert fm(severity=5, occurrence=4, detection=4).priority(100) == "Low"


@pytest.mark.parametrize("kw", [dict(severity=0), dict(occurrence=11), dict(detection=5.5), dict(special_char="XX")])
def test_invalid_ratings_rejected(kw):
    with pytest.raises(ValueError):
        fm(**kw)


def test_same_rpn_different_risk():
    a, b = fm(severity=10, occurrence=2, detection=5), fm(severity=4, occurrence=5, detection=5)
    assert a.rpn == b.rpn == 100
    assert a.priority() == "High" and b.priority() == "Medium"


def test_sample_ranking_puts_severity_9_first(modes):
    df = pfmea.ranked(modes)
    assert list(df["id"][:2]) == ["F7", "F5"]
    assert df.loc[df.id == "F4", "rpn"].item() == 192
    assert df["priority"].value_counts().to_dict() == {"Medium": 3, "High": 2, "Low": 2}


# -------------------------------------------------- traceability: shipped data
def test_sample_documents_are_consistent(modes, plan, dims):
    assert controlplan.check_pfmea_coverage(modes, plan) == []
    assert controlplan.check_stack_assumptions(dims, plan) == []


# ------------------------------------------------- traceability: broken plans
def test_uncovered_special_characteristic_is_error(modes, plan):
    plan = [i for i in plan if "F7" not in i.pfmea_ids]
    (f,) = controlplan.check_pfmea_coverage(modes, plan)
    assert f.level == "error" and "F7" in f.message and "CC" in f.message


def test_uncovered_medium_priority_is_error(modes, plan):
    plan = [i for i in plan if "F4" not in i.pfmea_ids]
    (f,) = controlplan.check_pfmea_coverage(modes, plan)
    assert "F4" in f.message and "Medium" in f.message


def test_unknown_pfmea_reference_is_warning(modes, plan):
    plan = plan + [replace(plan[0], characteristic="ghost", pfmea_id="F99", stack_dimension="")]
    (f,) = controlplan.check_pfmea_coverage(modes, plan)
    assert f.level == "warning" and "F99" in f.message


def test_control_plan_must_require_assumed_cp(dims, plan):
    plan = [replace(i, required_cpk=1.0) if i.stack_dimension == "Housing bore depth (A)" else i for i in plan]
    (f,) = controlplan.check_stack_assumptions(dims, plan)
    assert f.level == "error" and "assumes Cp 1.33" in f.message


def test_missing_line_for_capable_dimension_is_error(dims, plan):
    plan = [i for i in plan if i.stack_dimension != "Spacer length (C)"]
    (f,) = controlplan.check_stack_assumptions(dims, plan)
    assert f.level == "error" and "Spacer" in f.message


def test_missing_line_for_cp1_dimension_is_warning(dims, plan):
    plan = [i for i in plan if i.stack_dimension != "Bearing 1 width (B)"]
    (f,) = controlplan.check_stack_assumptions(dims, plan)
    assert f.level == "warning"


def test_spec_mismatch_is_error(dims, plan):
    plan = [replace(i, usl=53.40) if i.stack_dimension == "Housing bore depth (A)" else i for i in plan]
    (f,) = controlplan.check_stack_assumptions(dims, plan)
    assert "does not match" in f.message


def test_frames_round_trip(modes, plan):
    assert pfmea.from_frame(pfmea.to_frame(modes)) == modes
    assert controlplan.from_frame(controlplan.to_frame(plan)) == plan
