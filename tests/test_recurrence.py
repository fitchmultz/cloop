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

        with sqlite3.connect(settings.core_db_path) as conn:
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
