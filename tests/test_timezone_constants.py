"""Tests for timezone constants consistency.

Purpose:
    Verify that timezone constants defined in constants.py are consistent
    and correctly used across the codebase.

Responsibilities:
    - Validate constant ranges align with documented purposes
    - Verify OFFSET_TO_TIMEZONE keys are within RRULE range
    - Ensure no drift between constants and usage sites
"""

from cloop.constants import (
    MAX_TZ_OFFSET_MIN,
    MIN_TZ_OFFSET_MIN,
    OFFSET_TO_TIMEZONE,
    RRULE_MAX_TZ_OFFSET_MIN,
    RRULE_MIN_TZ_OFFSET_MIN,
)


class TestTimezoneConstants:
    """Tests for timezone constant definitions."""

    def test_python_tz_range_within_24_hours(self) -> None:
        """Python timezone range must be strictly within +/-24 hours."""
        # Python's timezone requires offsets strictly between -24 and +24 hours
        assert MIN_TZ_OFFSET_MIN == -1439  # -23:59
        assert MAX_TZ_OFFSET_MIN == 1439  # +23:59
        assert MIN_TZ_OFFSET_MIN > -1440  # Not -24 hours exactly
        assert MAX_TZ_OFFSET_MIN < 1440  # Not +24 hours exactly

    def test_rrule_tz_range_matches_real_world(self) -> None:
        """RRULE timezone range matches real-world IANA limits."""
        # Real-world timezones range from UTC-12 to UTC+14
        assert RRULE_MIN_TZ_OFFSET_MIN == -720  # -12 hours
        assert RRULE_MAX_TZ_OFFSET_MIN == 840  # +14 hours

    def test_rrule_range_within_python_range(self) -> None:
        """RRULE range must be within Python's acceptable range."""
        # The IANA range should be a subset of Python's timezone range
        assert RRULE_MIN_TZ_OFFSET_MIN >= MIN_TZ_OFFSET_MIN
        assert RRULE_MAX_TZ_OFFSET_MIN <= MAX_TZ_OFFSET_MIN

    def test_offset_to_timezone_keys_within_rrule_range(self) -> None:
        """All OFFSET_TO_TIMEZONE keys must be within RRULE valid range."""
        for offset in OFFSET_TO_TIMEZONE.keys():
            assert RRULE_MIN_TZ_OFFSET_MIN <= offset <= RRULE_MAX_TZ_OFFSET_MIN, (
                f"OFFSET_TO_TIMEZONE key {offset} is outside valid RRULE range "
                f"[{RRULE_MIN_TZ_OFFSET_MIN}, {RRULE_MAX_TZ_OFFSET_MIN}]"
            )

    def test_offset_to_timezone_has_common_offsets(self) -> None:
        """OFFSET_TO_TIMEZONE includes common timezone offsets."""
        # Major timezone offsets that should be present
        assert 0 in OFFSET_TO_TIMEZONE  # UTC
        assert -480 in OFFSET_TO_TIMEZONE  # PST
        assert -300 in OFFSET_TO_TIMEZONE  # EST
        assert 60 in OFFSET_TO_TIMEZONE  # CET
        assert 540 in OFFSET_TO_TIMEZONE  # JST


class TestTimezoneConstantsImport:
    """Tests that constants are correctly imported at usage sites."""

    def test_models_imports_tz_constants(self) -> None:
        """loops/models.py imports timezone constants from constants.py."""
        from cloop.loops import models

        # These should be the same objects (imported, not redefined)
        assert models.MIN_TZ_OFFSET_MIN is MIN_TZ_OFFSET_MIN
        assert models.MAX_TZ_OFFSET_MIN is MAX_TZ_OFFSET_MIN

    def test_recurrence_imports_tz_constants(self) -> None:
        """loops/recurrence.py imports timezone constants from constants.py."""
        from cloop.loops import recurrence

        # These should be the same objects (imported, not redefined)
        assert recurrence.OFFSET_TO_TIMEZONE is OFFSET_TO_TIMEZONE
        assert recurrence.RRULE_MIN_TZ_OFFSET_MIN is RRULE_MIN_TZ_OFFSET_MIN
        assert recurrence.RRULE_MAX_TZ_OFFSET_MIN is RRULE_MAX_TZ_OFFSET_MIN
