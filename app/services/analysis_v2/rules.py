HEAT_IMPACT_TEMP_C = 28.0
HYDRATION_RISK_TEMP_C = 24.0
HYDRATION_RISK_DURATION_SEC = 4500

DURATION_OVER_TARGET_RATIO = 1.15
DISTANCE_OVER_TARGET_RATIO = 1.15
ELEVATION_OVER_TARGET_RATIO = 1.20

HIGH_AVG_HR_PCT_OF_MAX = 0.88
AEROBIC_CONTROL_EASY_MAX = 0.78
AEROBIC_CONTROL_MODERATE_MAX = 0.88

PACE_INSTABILITY_CV_THRESHOLD = 0.08
POWER_INSTABILITY_CV_THRESHOLD = 0.10
CADENCE_INSTABILITY_CV_THRESHOLD = 0.06

CARDIAC_DRIFT_HR_DELTA_RATIO = 0.05
CARDIAC_DRIFT_PACE_CV_MAX = 0.08

TARGET_MARGIN_HR = 5
TARGET_MARGIN_POWER = 10
TARGET_MARGIN_PACE_SEC = 10

LAP_MATCH_MIN_COVERAGE_FOR_REVIEW = 0.5


def exported_thresholds() -> dict[str, float]:
    return {
        "heat_impact_temp_c": HEAT_IMPACT_TEMP_C,
        "hydration_risk_temp_c": HYDRATION_RISK_TEMP_C,
        "hydration_risk_duration_sec": HYDRATION_RISK_DURATION_SEC,
        "duration_over_target_ratio": DURATION_OVER_TARGET_RATIO,
        "distance_over_target_ratio": DISTANCE_OVER_TARGET_RATIO,
        "elevation_over_target_ratio": ELEVATION_OVER_TARGET_RATIO,
        "high_avg_hr_pct_of_max": HIGH_AVG_HR_PCT_OF_MAX,
        "aerobic_control_easy_max": AEROBIC_CONTROL_EASY_MAX,
        "aerobic_control_moderate_max": AEROBIC_CONTROL_MODERATE_MAX,
        "pace_instability_cv_threshold": PACE_INSTABILITY_CV_THRESHOLD,
        "power_instability_cv_threshold": POWER_INSTABILITY_CV_THRESHOLD,
        "cadence_instability_cv_threshold": CADENCE_INSTABILITY_CV_THRESHOLD,
        "cardiac_drift_hr_delta_ratio": CARDIAC_DRIFT_HR_DELTA_RATIO,
        "cardiac_drift_pace_cv_max": CARDIAC_DRIFT_PACE_CV_MAX,
        "target_margin_hr": TARGET_MARGIN_HR,
        "target_margin_power": TARGET_MARGIN_POWER,
        "target_margin_pace_sec": TARGET_MARGIN_PACE_SEC,
        "lap_match_min_coverage_for_review": LAP_MATCH_MIN_COVERAGE_FOR_REVIEW,
    }
