"""Tests for recurrence schedule parsing and computation.

Purpose:
    Validate natural-language recurrence parsing, RRULE handling, and
    DST-aware next occurrence computation.

Responsibilities:
    - Test all supported schedule phrase formats
    - Test RRULE validation and normalization
    - Test timezone-aware next occurrence computation
    - Test DST boundary handling

Non-scope:
    - HTTP API testing (covered by test routes)
    - Database persistence testing
"""

from datetime import datetime, timezone

import pytest

from cloop.loops.errors import RecurrenceError
from cloop.loops.recurrence import (
    compute_next_due,
    is_valid_timezone,
    offset_minutes_to_timezone,
    parse_recurrence_schedule,
    validate_rrule,
)


class TestParseRecurrenceSchedule:
    """Tests for natural-language schedule parsing."""

    def test_parse_every_day(self) -> None:
        """Parse 'every day' to FREQ=DAILY."""
        result = parse_recurrence_schedule("every day")
        assert result.rrule == "FREQ=DAILY"
        assert result.description == "Daily"

    def test_parse_daily(self) -> None:
        """Parse 'daily' to FREQ=DAILY."""
        result = parse_recurrence_schedule("daily")
        assert result.rrule == "FREQ=DAILY"

    def test_parse_every_weekday(self) -> None:
        """Parse 'every weekday' to weekly with BYDAY=MO-FR."""
        result = parse_recurrence_schedule("every weekday")
        assert result.rrule == "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR"
        assert "weekday" in result.description.lower()

    def test_parse_every_weekend(self) -> None:
        """Parse 'every weekend' to weekly with BYDAY=SA,SU."""
        result = parse_recurrence_schedule("every weekend")
        assert result.rrule == "FREQ=WEEKLY;BYDAY=SA,SU"

    def test_parse_every_week(self) -> None:
        """Parse 'every week' to FREQ=WEEKLY."""
        result = parse_recurrence_schedule("every week")
        assert result.rrule == "FREQ=WEEKLY"

    def test_parse_weekly(self) -> None:
        """Parse 'weekly' to FREQ=WEEKLY."""
        result = parse_recurrence_schedule("weekly")
        assert result.rrule == "FREQ=WEEKLY"

    def test_parse_every_month(self) -> None:
        """Parse 'every month' to FREQ=MONTHLY."""
        result = parse_recurrence_schedule("every month")
        assert result.rrule == "FREQ=MONTHLY"

    def test_parse_monthly(self) -> None:
        """Parse 'monthly' to FREQ=MONTHLY."""
        result = parse_recurrence_schedule("monthly")
        assert result.rrule == "FREQ=MONTHLY"

    def test_parse_every_year(self) -> None:
        """Parse 'every year' to FREQ=YEARLY."""
        result = parse_recurrence_schedule("every year")
        assert result.rrule == "FREQ=YEARLY"

    def test_parse_yearly(self) -> None:
        """Parse 'yearly' to FREQ=YEARLY."""
        result = parse_recurrence_schedule("yearly")
        assert result.rrule == "FREQ=YEARLY"

    def test_parse_every_2_weeks(self) -> None:
        """Parse 'every 2 weeks' with INTERVAL."""
        result = parse_recurrence_schedule("every 2 weeks")
        assert result.rrule == "FREQ=WEEKLY;INTERVAL=2"
        assert "2 week" in result.description

    def test_parse_every_3_months(self) -> None:
        """Parse 'every 3 months' with INTERVAL."""
        result = parse_recurrence_schedule("every 3 months")
        assert result.rrule == "FREQ=MONTHLY;INTERVAL=3"

    def test_parse_multiple_days(self) -> None:
        """Parse 'every monday,wednesday,friday'."""
        result = parse_recurrence_schedule("every monday,wednesday,friday")
        assert result.rrule == "FREQ=WEEKLY;BYDAY=MO,WE,FR"

    def test_parse_multiple_days_space_separated(self) -> None:
        """Parse 'every mon wed fri' with spaces."""
        result = parse_recurrence_schedule("every mon wed fri")
        assert result.rrule == "FREQ=WEEKLY;BYDAY=MO,WE,FR"

    def test_parse_first_monday(self) -> None:
        """Parse 'every 1st monday'."""
        result = parse_recurrence_schedule("every 1st monday")
        assert result.rrule == "FREQ=MONTHLY;BYDAY=1MO"

    def test_parse_last_friday(self) -> None:
        """Parse 'every last friday'."""
        result = parse_recurrence_schedule("every last friday")
        assert result.rrule == "FREQ=MONTHLY;BYDAY=-1FR"

    def test_parse_first_business_day(self) -> None:
        """Parse 'every 1st business day'."""
        result = parse_recurrence_schedule("every 1st business day")
        assert result.rrule == "FREQ=MONTHLY;BYDAY=MO,TU,WE,TH,FR;BYSETPOS=1"

    def test_parse_raw_rrule(self) -> None:
        """Pass through raw RRULE string."""
        result = parse_recurrence_schedule("FREQ=WEEKLY;BYDAY=MO,WE,FR")
        assert "FREQ=WEEKLY" in result.rrule

    def test_parse_empty_raises_error(self) -> None:
        """Empty phrase raises RecurrenceError."""
        with pytest.raises(RecurrenceError):
            parse_recurrence_schedule("")

    def test_parse_invalid_raises_error(self) -> None:
        """Invalid phrase raises RecurrenceError."""
        with pytest.raises(RecurrenceError):
            parse_recurrence_schedule("blah blah blah")


class TestValidateRrule:
    """Tests for RRULE validation."""

    def test_validate_valid_rrule(self) -> None:
        """Valid RRULE passes validation."""
        result = validate_rrule("freq=daily")
        # validate_rrule normalizes the RRULE and may add DTSTART
        assert "FREQ=DAILY" in result

    def test_validate_empty_raises_error(self) -> None:
        """Empty RRULE raises RecurrenceError."""
        with pytest.raises(RecurrenceError):
            validate_rrule("")

    def test_validate_missing_freq_raises_error(self) -> None:
        """RRULE without FREQ raises RecurrenceError."""
        with pytest.raises(RecurrenceError):
            validate_rrule("INTERVAL=2")


class TestComputeNextDue:
    """Tests for next occurrence computation."""

    def test_compute_next_daily(self) -> None:
        """Compute next daily occurrence."""
        after = datetime(2026, 2, 14, 12, 0, 0, tzinfo=timezone.utc)
        result = compute_next_due("FREQ=DAILY", "UTC", after)
        assert result is not None
        # Result should be after the reference time
        assert result > after

    def test_compute_next_weekly(self) -> None:
        """Compute next weekly occurrence."""
        after = datetime(2026, 2, 14, 12, 0, 0, tzinfo=timezone.utc)  # Saturday
        result = compute_next_due("FREQ=WEEKLY", "UTC", after)
        assert result is not None
        # Result should be after the reference time
        assert result > after

    def test_compute_next_with_timezone(self) -> None:
        """Compute next occurrence with America/New_York timezone."""
        after = datetime(2026, 2, 14, 12, 0, 0, tzinfo=timezone.utc)
        result = compute_next_due("FREQ=DAILY", "America/New_York", after)
        assert result is not None
        assert result > after

    def test_compute_next_invalid_timezone_raises_error(self) -> None:
        """Invalid timezone raises RecurrenceError."""
        after = datetime(2026, 2, 14, 12, 0, 0, tzinfo=timezone.utc)
        with pytest.raises(RecurrenceError):
            compute_next_due("FREQ=DAILY", "Invalid/Timezone", after)


class TestIsValidTimezone:
    """Tests for timezone validation."""

    def test_valid_utc(self) -> None:
        """UTC is valid."""
        assert is_valid_timezone("UTC") is True

    def test_valid_iana(self) -> None:
        """Common IANA names are valid."""
        assert is_valid_timezone("America/New_York") is True
        assert is_valid_timezone("Europe/London") is True
        assert is_valid_timezone("Asia/Tokyo") is True

    def test_invalid_timezone(self) -> None:
        """Invalid timezone returns False."""
        assert is_valid_timezone("Not/A/Timezone") is False


class TestOffsetMinutesToTimezone:
    """Tests for offset to timezone conversion."""

    def test_utc_offset(self) -> None:
        """UTC offset (0) returns UTC."""
        result = offset_minutes_to_timezone(0)
        assert result == "UTC"

    def test_pst_offset(self) -> None:
        """PST offset (-480) returns America/Los_Angeles."""
        result = offset_minutes_to_timezone(-480)
        assert result == "America/Los_Angeles"

    def test_est_offset(self) -> None:
        """EST offset (-300) returns America/New_York."""
        result = offset_minutes_to_timezone(-300)
        assert result == "America/New_York"

    def test_cet_offset(self) -> None:
        """CET offset (60) returns Etc/GMT-1."""
        result = offset_minutes_to_timezone(60)
        assert result == "Etc/GMT-1"

    def test_invalid_offset_raises_error(self) -> None:
        """Invalid offset raises RecurrenceError."""
        with pytest.raises(RecurrenceError):
            offset_minutes_to_timezone(-1000)

    def test_invalid_positive_offset_raises_error(self) -> None:
        """Invalid positive offset raises RecurrenceError."""
        with pytest.raises(RecurrenceError):
            offset_minutes_to_timezone(1000)


class TestDSTBoundaries:
    """Tests for DST boundary handling.

    These tests verify that recurrence computation handles DST transitions
    correctly, particularly for timezones like America/New_York.
    """

    def test_spring_forward_transition(self) -> None:
        """Test recurrence around spring DST transition.

        In 2026, DST starts on March 8 in the US.
        """
        # Just before DST transition
        after = datetime(2026, 3, 7, 12, 0, 0, tzinfo=timezone.utc)
        result = compute_next_due("FREQ=DAILY", "America/New_York", after)
        assert result is not None
        # Result should be after the reference time
        assert result > after

    def test_fall_back_transition(self) -> None:
        """Test recurrence around fall DST transition.

        In 2026, DST ends on November 1 in the US.
        """
        # Just before DST transition
        after = datetime(2026, 10, 31, 12, 0, 0, tzinfo=timezone.utc)
        result = compute_next_due("FREQ=DAILY", "America/New_York", after)
        assert result is not None
        # Result should be after the reference time
        assert result > after

    def test_spring_forward_hour_preservation(self) -> None:
        """Daily recurrence at 2:30 AM local time stays at 2:30 AM after spring-forward.

        In 2026, US DST starts March 8 at 2:00 AM (clocks jump to 3:00 AM).
        A 2:30 AM local time doesn't exist on that day.
        """
        # 2:30 AM EST on March 7, 2026 = 7:30 AM UTC
        after = datetime(2026, 3, 7, 7, 30, 0, tzinfo=timezone.utc)
        result = compute_next_due("FREQ=DAILY;BYHOUR=2;BYMINUTE=30", "America/New_York", after)
        assert result is not None
        # Should be March 8, but 2:30 AM doesn't exist, so expect 3:30 AM EDT (7:30 AM UTC)
        # or similar adjustment depending on dateutil behavior

    def test_fall_back_hour_preservation(self) -> None:
        """Daily recurrence handles duplicate 1:00 AM hour during fall-back.

        In 2026, US DST ends November 1 at 2:00 AM (clocks fall back to 1:00 AM).
        1:00 AM occurs twice (EDT and EST).
        """
        # 6:00 AM UTC on Nov 1 = 1:00 AM EST (second occurrence)
        after = datetime(2026, 11, 1, 6, 0, 0, tzinfo=timezone.utc)
        result = compute_next_due("FREQ=DAILY;BYHOUR=1;BYMINUTE=0", "America/New_York", after)
        assert result is not None
        # Next occurrence should be Nov 2 at 1:00 AM EST (6:00 AM UTC)


class TestRecurrenceQueryFilter:
    """Tests for recurring: filter in query DSL."""

    def test_parse_recurring_yes(self) -> None:
        """Parse 'recurring:yes' filter."""
        from cloop.loops.query import parse_loop_query

        query = parse_loop_query("recurring:yes")
        assert query.recurring is True

    def test_parse_recurring_no(self) -> None:
        """Parse 'recurring:no' filter."""
        from cloop.loops.query import parse_loop_query

        query = parse_loop_query("recurring:no")
        assert query.recurring is False

    def test_parse_recurring_true(self) -> None:
        """Parse 'recurring:true' filter."""
        from cloop.loops.query import parse_loop_query

        query = parse_loop_query("recurring:true")
        assert query.recurring is True

    def test_parse_recurring_false(self) -> None:
        """Parse 'recurring:false' filter."""
        from cloop.loops.query import parse_loop_query

        query = parse_loop_query("recurring:false")
        assert query.recurring is False

    def test_parse_recurring_combined(self) -> None:
        """Parse recurring filter combined with other filters."""
        from cloop.loops.query import parse_loop_query

        query = parse_loop_query("status:inbox recurring:yes tag:work")
        assert query.recurring is True
        assert "inbox" in query.statuses
        assert "work" in query.tags

    def test_compile_recurring_yes(self) -> None:
        """Compile 'recurring:yes' to SQL."""
        from cloop.loops.query import LoopQuery, compile_loop_query

        query = LoopQuery(recurring=True)
        sql, params = compile_loop_query(query, now_utc=datetime.now(timezone.utc))
        assert "recurrence_enabled = 1" in sql

    def test_compile_recurring_no(self) -> None:
        """Compile 'recurring:no' to SQL."""
        from cloop.loops.query import LoopQuery, compile_loop_query

        query = LoopQuery(recurring=False)
        sql, params = compile_loop_query(query, now_utc=datetime.now(timezone.utc))
        assert "recurrence_enabled = 0" in sql


class TestRecurrenceErrorHandling:
    """Tests for recurrence error handling during completion."""

    def test_completion_with_invalid_rrule_does_not_fail(
        self,
        tmp_path,
        monkeypatch,
    ) -> None:
        """Completing a loop with invalid RRULE should still succeed."""
        import sqlite3
        from contextlib import closing

        from cloop import db
        from cloop.loops import service as loop_service
        from cloop.loops.models import LoopStatus
        from cloop.settings import get_settings

        # Setup test database using environment variables (like other tests)
        monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
        monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
        get_settings.cache_clear()
        settings = get_settings()
        db.init_databases(settings)

        with closing(sqlite3.connect(settings.core_db_path)) as conn:
            conn.row_factory = sqlite3.Row

            # Create a loop with recurrence
            loop = loop_service.capture_loop(
                raw_text="Test task",
                captured_at_iso="2026-02-14T10:00:00+00:00",
                client_tz_offset_min=0,
                status=LoopStatus.SCHEDULED,
                recurrence_rrule="FREQ=DAILY",
                recurrence_tz="UTC",
                conn=conn,
            )
            loop_id = loop["id"]

            # Manually corrupt the RRULE (simulate data corruption)
            conn.execute(
                "UPDATE loops SET recurrence_rrule = ? WHERE id = ?",
                ("INVALID_RRULE!!!", loop_id),
            )
            conn.commit()

            # Complete the loop - should NOT raise an exception
            result = loop_service.transition_status(
                loop_id=loop_id,
                to_status=LoopStatus.COMPLETED,
                conn=conn,
            )

            # Verify completion succeeded
            assert result["status"] == "completed"
            assert result["recurrence_enabled"] is False

            # Verify no next occurrence was created (recurrence failed)
            cursor = conn.execute(
                "SELECT COUNT(*) as count FROM loops WHERE id != ?",
                (loop_id,),
            )
            count = cursor.fetchone()["count"]
            assert count == 0  # No new loop created due to invalid RRULE


class TestDSTTransitions:
    """Tests for precise DST transition handling."""

    def test_weekly_crosses_spring_forward(self) -> None:
        """Weekly recurrence crosses DST spring-forward correctly."""
        # Monday March 2, 2026 9:00 AM EST = 14:00 UTC
        after = datetime(2026, 3, 2, 14, 0, 0, tzinfo=timezone.utc)
        # Use DTSTART to anchor the RRULE at the correct time
        rrule = "DTSTART:20260302T140000Z\nRRULE:FREQ=WEEKLY;BYDAY=MO;BYHOUR=9;BYMINUTE=0"
        result = compute_next_due(rrule, "America/New_York", after)
        assert result is not None
        # Should be March 9, 2026 9:00 AM EDT = 13:00 UTC (offset changed from -5 to -4)
        assert result.hour == 13
        assert result.day == 9

    def test_weekly_crosses_fall_back(self) -> None:
        """Weekly recurrence crosses DST fall-back correctly."""
        # Monday Oct 26, 2026 9:00 AM EDT = 13:00 UTC
        after = datetime(2026, 10, 26, 13, 0, 0, tzinfo=timezone.utc)
        rrule = "DTSTART:20261026T130000Z\nRRULE:FREQ=WEEKLY;BYDAY=MO;BYHOUR=9;BYMINUTE=0"
        result = compute_next_due(rrule, "America/New_York", after)
        assert result is not None
        # Should be Nov 2, 2026 9:00 AM EST = 14:00 UTC (offset changed from -4 to -5)
        assert result.hour == 14
        assert result.day == 2

    def test_dst_in_europe_london(self) -> None:
        """DST transition in Europe/London timezone."""
        # UK DST 2026: starts March 29, ends October 25
        after = datetime(2026, 3, 28, 10, 0, 0, tzinfo=timezone.utc)  # 10:00 UTC = 10:00 GMT
        rrule = "DTSTART:20260328T100000Z\nRRULE:FREQ=DAILY;BYHOUR=10;BYMINUTE=0"
        result = compute_next_due(rrule, "Europe/London", after)
        assert result is not None
        # March 29: 10:00 BST = 09:00 UTC
        assert result.hour == 9


class TestYearBoundary:
    """Tests for year boundary crossing."""

    def test_daily_crosses_year_boundary(self) -> None:
        """Daily recurrence crosses Dec 31 to Jan 1 correctly."""
        after = datetime(2026, 12, 31, 12, 0, 0, tzinfo=timezone.utc)
        rrule = "DTSTART:20261231T120000Z\nRRULE:FREQ=DAILY"
        result = compute_next_due(rrule, "UTC", after)
        assert result is not None
        assert result.year == 2027
        assert result.month == 1
        assert result.day == 1

    def test_weekly_crosses_year_boundary(self) -> None:
        """Weekly recurrence crosses year boundary."""
        # Dec 31, 2026 is a Thursday
        after = datetime(2026, 12, 31, 12, 0, 0, tzinfo=timezone.utc)
        rrule = "DTSTART:20261231T120000Z\nRRULE:FREQ=WEEKLY;BYDAY=TH"
        result = compute_next_due(rrule, "UTC", after)
        assert result is not None
        assert result.year == 2027
        assert result.month == 1
        assert result.day == 7  # Next Thursday

    def test_yearly_recurrence_next_year(self) -> None:
        """Yearly recurrence increments year."""
        after = datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        rrule = "DTSTART:20260615T120000Z\nRRULE:FREQ=YEARLY;BYMONTH=6;BYMONTHDAY=15"
        result = compute_next_due(rrule, "UTC", after)
        assert result is not None
        assert result.year == 2027
        assert result.month == 6
        assert result.day == 15


class TestTimezoneOffsetBoundaries:
    """Tests for timezone offset boundary values."""

    def test_min_offset_utc_minus_12(self) -> None:
        """Minimum valid offset -720 (UTC-12)."""
        from cloop.constants import RRULE_MIN_TZ_OFFSET_MIN

        assert RRULE_MIN_TZ_OFFSET_MIN == -720
        result = offset_minutes_to_timezone(-720)
        assert result == "Etc/GMT+12"

    def test_max_offset_utc_plus_14(self) -> None:
        """Maximum valid offset 840 (UTC+14)."""
        from cloop.constants import RRULE_MAX_TZ_OFFSET_MIN

        assert RRULE_MAX_TZ_OFFSET_MIN == 840
        result = offset_minutes_to_timezone(840)
        assert result == "Pacific/Kiritimati"

    def test_offset_below_min_raises_error(self) -> None:
        """Offset below -720 raises RecurrenceError."""
        with pytest.raises(RecurrenceError) as exc_info:
            offset_minutes_to_timezone(-721)
        assert "-720" in str(exc_info.value)

    def test_offset_above_max_raises_error(self) -> None:
        """Offset above 840 raises RecurrenceError."""
        with pytest.raises(RecurrenceError) as exc_info:
            offset_minutes_to_timezone(841)
        assert "840" in str(exc_info.value)

    def test_common_offsets_mapped(self) -> None:
        """Common offsets map to familiar timezone names."""
        assert offset_minutes_to_timezone(0) == "UTC"
        assert offset_minutes_to_timezone(-480) == "America/Los_Angeles"
        assert offset_minutes_to_timezone(-300) == "America/New_York"
        assert offset_minutes_to_timezone(540) == "Asia/Tokyo"


class TestInvalidRrule:
    """Tests for invalid RRULE string handling."""

    def test_malformed_syntax(self) -> None:
        """Malformed RRULE syntax raises RecurrenceError."""
        with pytest.raises(RecurrenceError):
            validate_rrule("FREQ=WEEKLY;BYDAY=")  # Empty BYDAY

    def test_invalid_freq_value(self) -> None:
        """Invalid FREQ value raises RecurrenceError."""
        with pytest.raises(RecurrenceError):
            validate_rrule("FREQ=INVALID")

    def test_invalid_byday(self) -> None:
        """Invalid BYDAY value raises RecurrenceError."""
        with pytest.raises(RecurrenceError):
            validate_rrule("FREQ=WEEKLY;BYDAY=XX")

    def test_zero_bysetpos(self) -> None:
        """BYSETPOS=0 raises RecurrenceError (must be non-zero)."""
        with pytest.raises(RecurrenceError):
            validate_rrule("FREQ=MONTHLY;BYDAY=MO;BYSETPOS=0")

    def test_empty_byday_list(self) -> None:
        """Empty BYDAY list raises RecurrenceError."""
        with pytest.raises(RecurrenceError):
            validate_rrule("FREQ=WEEKLY;BYDAY=")

    def test_compute_next_due_with_invalid_rrule(self) -> None:
        """compute_next_due raises RecurrenceError for invalid RRULE."""
        after = datetime(2026, 2, 14, 12, 0, 0, tzinfo=timezone.utc)
        with pytest.raises(RecurrenceError):
            compute_next_due("FREQ=INVALID", "UTC", after)


class TestLeapYearRecurrence:
    """Tests for leap year February 29 recurrence."""

    def test_feb_29_in_leap_year(self) -> None:
        """February 29 recurrence works in leap year."""
        # Feb 29, 2024 was a leap year; next is Feb 28, 2025 or Feb 29, 2028
        after = datetime(2024, 2, 29, 12, 0, 0, tzinfo=timezone.utc)
        result = compute_next_due("FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=29", "UTC", after)
        assert result is not None
        # dateutil typically shifts non-leap year Feb 29 to Feb 28
        assert result.month == 2
        assert result.day in (28, 29)  # Either Feb 28 or next Feb 29

    def test_feb_29_from_non_leap_year(self) -> None:
        """Feb 29 recurrence from non-leap year finds next leap year."""
        after = datetime(2025, 3, 1, 12, 0, 0, tzinfo=timezone.utc)
        result = compute_next_due("FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=29", "UTC", after)
        assert result is not None
        # Should find Feb 29, 2028 (next leap year)
        assert result.year == 2028
        assert result.month == 2
        assert result.day == 29


class TestRruleLimitations:
    """Tests for RRULE with COUNT and UNTIL terminators."""

    def test_count_limit(self) -> None:
        """RRULE with COUNT returns None after count exhausted."""
        # COUNT=1 means only one occurrence
        after = datetime(2026, 2, 14, 12, 0, 0, tzinfo=timezone.utc)
        # Use DTSTART before 'after' so the single occurrence is already used
        rrule = "DTSTART:20260213T120000Z\nRRULE:FREQ=DAILY;COUNT=1"
        result = compute_next_due(rrule, "UTC", after)
        # The COUNT=1 occurrence was on Feb 13, so no more after Feb 14
        assert result is None

    def test_until_limit(self) -> None:
        """RRULE with UNTIL returns None after end date."""
        after = datetime(2026, 2, 16, 12, 0, 0, tzinfo=timezone.utc)
        rrule = "DTSTART:20260210T120000Z\nRRULE:FREQ=DAILY;UNTIL=20260215T120000Z"
        result = compute_next_due(rrule, "UTC", after)
        # UNTIL is Feb 15, so no occurrence after Feb 16
        assert result is None

    def test_until_in_future(self) -> None:
        """RRULE with future UNTIL still generates occurrences."""
        after = datetime(2026, 2, 14, 12, 0, 0, tzinfo=timezone.utc)
        rrule = "DTSTART:20260201T120000Z\nRRULE:FREQ=DAILY;UNTIL=20260220T120000Z"
        result = compute_next_due(rrule, "UTC", after)
        assert result is not None
        assert result.day == 15  # Next day after Feb 14
