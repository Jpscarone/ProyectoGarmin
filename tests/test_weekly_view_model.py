from __future__ import annotations

from app.routers.analysis import _weekly_intensity_indicator


def test_weekly_intensity_indicator_labels() -> None:
    indicator = _weekly_intensity_indicator(
        {"weekly_intensity_balance_score": 82},
        {"intensity_distribution_imbalance_flag": False},
        {"intensity_zone_summary": {"pct_z2": 40.0, "pct_z3": 20.0, "pct_z4_plus": 10.0, "pct_z4": 8.0}},
    )
    assert indicator["label"] == "equilibrado"

    indicator = _weekly_intensity_indicator(
        {"weekly_intensity_balance_score": 55},
        {"intensity_distribution_imbalance_flag": False},
        {"intensity_zone_summary": {"pct_z2": 22.0, "pct_z3": 35.0, "pct_z4_plus": 18.0, "pct_z4": 10.0}},
    )
    assert indicator["label"] == "intermedio"

    indicator = _weekly_intensity_indicator(
        {"weekly_intensity_balance_score": 30},
        {"intensity_distribution_imbalance_flag": True},
        {"intensity_zone_summary": {"pct_z2": 5.0, "pct_z3": 55.0, "pct_z4_plus": 35.0, "pct_z4": 28.0}},
    )
    assert indicator["label"] == "desbalanceado"
