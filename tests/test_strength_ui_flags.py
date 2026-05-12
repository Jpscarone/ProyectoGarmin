from __future__ import annotations

from app.routers.planned_sessions import _sport_ui_capabilities


def test_strength_ui_flags_hide_endurance_fields() -> None:
    flags = _sport_ui_capabilities("strength")

    assert flags["is_strength"] is True
    assert flags["hide_endurance_distance"] is True
    assert flags["hide_endurance_targets"] is True
    assert flags["builder_supported"] is False
    assert "gimnasio" in flags["builder_message"].lower()


def test_running_ui_flags_keep_endurance_fields() -> None:
    flags = _sport_ui_capabilities("running")

    assert flags["is_strength"] is False
    assert flags["hide_endurance_distance"] is False
    assert flags["hide_endurance_targets"] is False
    assert flags["builder_supported"] is True
