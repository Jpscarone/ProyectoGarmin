from __future__ import annotations

import unittest
from datetime import date

from app.services.session_import_parser import ImportRepeat, parse_session_import_text
from app.services.session_import_validator import validate_import_payload


class SessionImportParserTests(unittest.TestCase):
    def _assert_has_error(self, errors, contains: str) -> None:
        messages = [error.message for error in errors]
        self.assertTrue(any(contains in message for message in messages), f"No se encontro error con '{contains}'.")

    def test_session_simple_valid(self) -> None:
        raw = """SESSION
DATE: 2026-04-05
SPORT: running
NAME: Fondo progresivo

BLOCK
VALUE: 20
UNIT: min
INTENSITY: hr
ZONE: z2

END"""
        parsed = parse_session_import_text(raw)
        self.assertEqual(parsed.errors, [])

        validation = validate_import_payload(sessions=parsed.sessions, groups=parsed.groups, base_date=None)
        self.assertEqual(validation.errors, [])

    def test_repeat_valid(self) -> None:
        raw = """SESSION
DATE: 2026-04-06
SPORT: running
NAME: Series 6x400

REPEAT
COUNT: 6

BLOCK
VALUE: 400
UNIT: m
INTENSITY: pace
ZONE: z4

END_REPEAT

END"""
        parsed = parse_session_import_text(raw)
        self.assertEqual(parsed.errors, [])
        self.assertEqual(len(parsed.sessions), 1)
        self.assertIsInstance(parsed.sessions[0].blocks[0], ImportRepeat)
        repeat = parsed.sessions[0].blocks[0]
        self.assertEqual(repeat.count, 6)

        validation = validate_import_payload(sessions=parsed.sessions, groups=parsed.groups, base_date=None)
        self.assertEqual(validation.errors, [])

    def test_group_date_inherited(self) -> None:
        raw = """SESSION_GROUP
NAME: Brick sabado
DATE: 2026-04-09

SESSION
SPORT: cycling
NAME: Bici base

BLOCK
VALUE: 90
UNIT: min
INTENSITY: power
ZONE: z2

END

END_GROUP"""
        parsed = parse_session_import_text(raw)
        self.assertEqual(parsed.errors, [])
        validation = validate_import_payload(sessions=parsed.sessions, groups=parsed.groups, base_date=None)
        self.assertEqual(validation.errors, [])

    def test_session_uses_base_date(self) -> None:
        raw = """SESSION
SPORT: running
NAME: Fondo base

BLOCK
VALUE: 45
UNIT: min
INTENSITY: hr
ZONE: z2

END"""
        parsed = parse_session_import_text(raw)
        validation = validate_import_payload(
            sessions=parsed.sessions,
            groups=parsed.groups,
            base_date=date(2026, 4, 5),
        )
        self.assertEqual(validation.errors, [])

    def test_invalid_date(self) -> None:
        raw = """SESSION
DATE: 2026-99-99
SPORT: running

BLOCK
VALUE: 20
UNIT: min
END"""
        parsed = parse_session_import_text(raw)
        validation = validate_import_payload(sessions=parsed.sessions, groups=parsed.groups, base_date=None)
        self._assert_has_error(validation.errors, "DATE invalida")

    def test_missing_sport(self) -> None:
        raw = """SESSION
DATE: 2026-04-05

BLOCK
VALUE: 20
UNIT: min
END"""
        parsed = parse_session_import_text(raw)
        validation = validate_import_payload(sessions=parsed.sessions, groups=parsed.groups, base_date=None)
        self._assert_has_error(validation.errors, "SPORT faltante")

    def test_invalid_unit(self) -> None:
        raw = """SESSION
DATE: 2026-04-05
SPORT: running

BLOCK
VALUE: 20
UNIT: foo
END"""
        parsed = parse_session_import_text(raw)
        validation = validate_import_payload(sessions=parsed.sessions, groups=parsed.groups, base_date=None)
        self._assert_has_error(validation.errors, "UNIT invalido")

    def test_invalid_repeat_count(self) -> None:
        raw = """SESSION
DATE: 2026-04-06
SPORT: running

REPEAT
COUNT: foo

BLOCK
VALUE: 400
UNIT: m
INTENSITY: pace
ZONE: z4

END_REPEAT
END"""
        parsed = parse_session_import_text(raw)
        validation = validate_import_payload(sessions=parsed.sessions, groups=parsed.groups, base_date=None)
        self._assert_has_error(validation.errors, "COUNT invalido")

    def test_end_without_session(self) -> None:
        raw = "END"
        parsed = parse_session_import_text(raw)
        self._assert_has_error(parsed.errors, "END sin SESSION")

    def test_end_repeat_without_repeat(self) -> None:
        raw = """SESSION
DATE: 2026-04-06
SPORT: running

END_REPEAT
END"""
        parsed = parse_session_import_text(raw)
        self._assert_has_error(parsed.errors, "END_REPEAT sin REPEAT")

    def test_end_group_without_group(self) -> None:
        raw = "END_GROUP"
        parsed = parse_session_import_text(raw)
        self._assert_has_error(parsed.errors, "END_GROUP sin SESSION_GROUP")

    def test_hr_custom_valid(self) -> None:
        raw = """SESSION
DATE: 2026-04-05
SPORT: running

BLOCK
VALUE: 10
UNIT: min
INTENSITY: hr
ZONE: custom
HR_MIN: 151
HR_MAX: 155

END"""
        parsed = parse_session_import_text(raw)
        validation = validate_import_payload(sessions=parsed.sessions, groups=parsed.groups, base_date=None)
        self.assertEqual(parsed.errors, [])
        self.assertEqual(validation.errors, [])

    def test_hr_custom_alias_fc_valid(self) -> None:
        raw = """SESSION
DATE: 2026-04-05
SPORT: running

BLOCK
VALUE: 10
UNIT: min
INTENSITY: hr
ZONE: custom
FC_MIN: 151
FC_MAX: 155

END"""
        parsed = parse_session_import_text(raw)
        validation = validate_import_payload(sessions=parsed.sessions, groups=parsed.groups, base_date=None)
        self.assertEqual(validation.errors, [])

    def test_pace_custom_valid(self) -> None:
        raw = """SESSION
DATE: 2026-04-05
SPORT: running

BLOCK
VALUE: 6
UNIT: min
INTENSITY: pace
ZONE: custom
PACE_MIN: 5:00
PACE_MAX: 5:10

END"""
        parsed = parse_session_import_text(raw)
        validation = validate_import_payload(sessions=parsed.sessions, groups=parsed.groups, base_date=None)
        self.assertEqual(validation.errors, [])

    def test_power_custom_valid(self) -> None:
        raw = """SESSION
DATE: 2026-04-05
SPORT: cycling

BLOCK
VALUE: 8
UNIT: min
INTENSITY: power
ZONE: custom
POWER_MIN: 280
POWER_MAX: 310

END"""
        parsed = parse_session_import_text(raw)
        validation = validate_import_payload(sessions=parsed.sessions, groups=parsed.groups, base_date=None)
        self.assertEqual(validation.errors, [])

    def test_hr_custom_requires_range(self) -> None:
        raw = """SESSION
DATE: 2026-04-05
SPORT: running

BLOCK
VALUE: 10
UNIT: min
INTENSITY: hr
ZONE: custom

END"""
        parsed = parse_session_import_text(raw)
        validation = validate_import_payload(sessions=parsed.sessions, groups=parsed.groups, base_date=None)
        self._assert_has_error(validation.errors, "requiere HR_MIN/HR_MAX")

    def test_pace_custom_invalid_format(self) -> None:
        raw = """SESSION
DATE: 2026-04-05
SPORT: running

BLOCK
VALUE: 6
UNIT: min
INTENSITY: pace
ZONE: custom
PACE_MIN: 5.00
PACE_MAX: 5:10

END"""
        parsed = parse_session_import_text(raw)
        validation = validate_import_payload(sessions=parsed.sessions, groups=parsed.groups, base_date=None)
        self._assert_has_error(validation.errors, "PACE_MIN/PACE_MAX")

    def test_custom_min_must_be_lower_than_max(self) -> None:
        raw = """SESSION
DATE: 2026-04-05
SPORT: running

BLOCK
VALUE: 10
UNIT: min
INTENSITY: hr
ZONE: custom
HR_MIN: 155
HR_MAX: 151

END"""
        parsed = parse_session_import_text(raw)
        validation = validate_import_payload(sessions=parsed.sessions, groups=parsed.groups, base_date=None)
        self._assert_has_error(validation.errors, "HR_MIN debe ser menor")

    def test_non_custom_zone_rejects_custom_fields(self) -> None:
        raw = """SESSION
DATE: 2026-04-05
SPORT: running

BLOCK
VALUE: 10
UNIT: min
INTENSITY: hr
ZONE: z2
HR_MIN: 151
HR_MAX: 155

END"""
        parsed = parse_session_import_text(raw)
        validation = validate_import_payload(sessions=parsed.sessions, groups=parsed.groups, base_date=None)
        self._assert_has_error(validation.errors, "Campos custom no permitidos")


if __name__ == "__main__":
    unittest.main()
