from __future__ import annotations

from app.services.analysis_v2.weekly_analysis_service import _weekly_intensity_balance_score, _weekly_intensity_imbalance_flag


def test_weekly_intensity_imbalance_flag_true() -> None:
    summary = {"pct_z2": 12.0, "pct_z3": 40.0, "pct_z4_plus": 30.0, "pct_z4": 26.0}
    assert _weekly_intensity_imbalance_flag(summary) is True


def test_weekly_intensity_balance_score_low() -> None:
    summary = {"pct_z2": 15.0, "pct_z3": 35.0, "pct_z4_plus": 30.0, "pct_z4": 28.0}
    score = _weekly_intensity_balance_score(summary)
    assert score is not None
    assert score < 70
