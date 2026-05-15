from __future__ import annotations

import unittest
from datetime import datetime, timezone

from app.utils.datetime_utils import get_app_timezone, now_local, to_local_date, to_local_datetime, today_local


class DatetimeUtilsTests(unittest.TestCase):
    @staticmethod
    def _tz_name(value) -> str:
        return getattr(value, "key", None) or str(value)

    def test_app_timezone_defaults_to_buenos_aires(self) -> None:
        self.assertEqual(self._tz_name(get_app_timezone()), "America/Argentina/Buenos_Aires")

    def test_now_local_uses_configured_timezone(self) -> None:
        local_now = now_local()
        self.assertEqual(self._tz_name(local_now.tzinfo), "America/Argentina/Buenos_Aires")

    def test_today_local_matches_localized_datetime(self) -> None:
        self.assertEqual(today_local(), now_local().date())

    def test_to_local_datetime_converts_utc_to_argentina_time(self) -> None:
        utc_value = datetime(2026, 5, 14, 20, 0, tzinfo=timezone.utc)

        local_value = to_local_datetime(utc_value)

        self.assertIsNotNone(local_value)
        assert local_value is not None
        self.assertEqual(local_value.hour, 17)
        self.assertEqual(local_value.minute, 0)
        self.assertEqual(self._tz_name(local_value.tzinfo), "America/Argentina/Buenos_Aires")

    def test_to_local_date_handles_near_midnight_utc(self) -> None:
        utc_value = datetime(2026, 5, 15, 1, 30, tzinfo=timezone.utc)

        local_date = to_local_date(utc_value)

        self.assertEqual(str(local_date), "2026-05-14")


if __name__ == "__main__":
    unittest.main()
