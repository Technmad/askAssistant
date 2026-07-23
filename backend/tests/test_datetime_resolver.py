from datetime import datetime, time

from app.nlu.datetime_resolver import (
    ResolvedRange,
    extract_time_of_day,
    parse_relative_date,
    resolve_instant,
    resolve_range,
)

# Fixed reference point for every test: Wednesday 2026-07-22, 10:00.
WED = datetime(2026, 7, 22, 10, 0)
# A second reference that lands ON a Friday, to exercise the same-day rule.
FRI = datetime(2026, 7, 24, 10, 0)


class TestExtractTimeOfDay:
    def test_12_hour_pm(self):
        assert extract_time_of_day("meet at 3pm") == time(15, 0)

    def test_12_hour_am_with_minutes(self):
        assert extract_time_of_day("9:30 am call") == time(9, 30)

    def test_12_hour_noon_edge_case(self):
        assert extract_time_of_day("12pm lunch") == time(12, 0)

    def test_12_hour_midnight_edge_case(self):
        assert extract_time_of_day("12am") == time(0, 0)

    def test_24_hour_form(self):
        assert extract_time_of_day("schedule for 15:00") == time(15, 0)

    def test_vague_morning_defaults_to_9am(self):
        assert extract_time_of_day("Monday morning") == time(9, 0)

    def test_vague_evening_defaults_to_6pm(self):
        assert extract_time_of_day("tomorrow evening") == time(18, 0)

    def test_explicit_time_wins_over_vague_word(self):
        assert extract_time_of_day("tomorrow evening at 9pm") == time(21, 0)

    def test_no_time_at_all_returns_none(self):
        assert extract_time_of_day("next Monday") is None


class TestParseRelativeDate:
    def test_tomorrow(self):
        assert parse_relative_date("tomorrow 3pm", WED) == datetime(2026, 7, 23).date()

    def test_day_after_tomorrow(self):
        # "tomorrow" is a substring of "day after tomorrow" -- must resolve
        # to +2 days, not silently match the bare "tomorrow" branch as +1.
        assert parse_relative_date("day after tomorrow 12pm", WED) == datetime(2026, 7, 24).date()

    def test_today(self):
        assert parse_relative_date("today at 5pm", WED) == datetime(2026, 7, 22).date()

    def test_bare_weekday_forward_in_week(self):
        # Wed -> nearest Monday is next week (5 days out)
        assert parse_relative_date("Monday", WED) == datetime(2026, 7, 27).date()

    def test_next_weekday_when_not_today_is_same_as_bare(self):
        # "next Monday" said on a Wednesday: no same-day ambiguity to resolve,
        # so it's just the nearest upcoming Monday -- matches common usage.
        assert parse_relative_date("next Monday", WED) == datetime(2026, 7, 27).date()

    def test_no_recognizable_date_returns_none(self):
        assert parse_relative_date("as soon as possible", WED) is None


class TestParseAbsoluteDate:
    # Found live: "schedule a meeting with asmita on 26 july 12 pm" asked
    # "What day should this be?" even though the day WAS given -- the
    # resolver only understood relative phrases, never an outright date.
    def test_day_then_month(self):
        assert parse_relative_date("26 july 12 pm", WED) == datetime(2026, 7, 26).date()

    def test_month_then_day(self):
        assert parse_relative_date("July 26 12pm", WED) == datetime(2026, 7, 26).date()

    def test_ordinal_suffix(self):
        assert parse_relative_date("26th July", WED) == datetime(2026, 7, 26).date()

    def test_explicit_year(self):
        assert parse_relative_date("July 26th, 2027", WED) == datetime(2027, 7, 26).date()

    def test_past_date_this_year_rolls_to_next_year(self):
        # WED is 2026-07-22 -- July 10 has already passed this year.
        assert parse_relative_date("10 July", WED) == datetime(2027, 7, 10).date()

    def test_resolve_instant_combines_absolute_date_and_time(self):
        assert resolve_instant("26 july 12 pm", WED) == datetime(2026, 7, 26, 12, 0)


class TestSameDayWeekdayRule:
    """The documented ambiguity: 'Friday' said on a Friday. §3."""

    def test_bare_weekday_today_time_not_yet_passed_means_today(self):
        result = resolve_instant("Friday 5pm", FRI)  # FRI is 10:00
        assert result == datetime(2026, 7, 24, 17, 0)

    def test_bare_weekday_today_time_already_passed_rolls_to_next_week(self):
        result = resolve_instant("Friday 9am", FRI)  # FRI is 10:00, 9am already passed
        assert result == datetime(2026, 7, 31, 9, 0)

    def test_next_weekday_today_always_skips_to_next_week_regardless_of_time(self):
        result = resolve_instant("next Friday 5pm", FRI)  # time hasn't passed, but "next" forces the skip
        assert result == datetime(2026, 7, 31, 17, 0)

    def test_this_weekday_today_behaves_like_bare_weekday(self):
        result = resolve_instant("this Friday 5pm", FRI)
        assert result == datetime(2026, 7, 24, 17, 0)


class TestResolveInstant:
    def test_tomorrow_3pm_exact(self):
        assert resolve_instant("tomorrow 3pm", WED) == datetime(2026, 7, 23, 15, 0)

    def test_next_monday_morning(self):
        assert resolve_instant("next Monday morning", WED) == datetime(2026, 7, 27, 9, 0)

    def test_missing_time_defaults_to_midnight(self):
        # No time-of-day mentioned at all -- fine for a task due date,
        # calendar-event callers must separately require a time slot.
        assert resolve_instant("next Monday", WED) == datetime(2026, 7, 27, 0, 0)

    def test_unparseable_phrase_returns_none(self):
        assert resolve_instant("whenever works", WED) is None


class TestResolveRange:
    def test_this_week_spans_today_through_sunday(self):
        result = resolve_range("this week", WED)
        assert result == ResolvedRange(
            start=datetime(2026, 7, 22, 0, 0),
            end=datetime(2026, 7, 26, 23, 59, 59),
        )

    def test_next_week_spans_monday_through_sunday(self):
        result = resolve_range("next week", WED)
        assert result == ResolvedRange(
            start=datetime(2026, 7, 27, 0, 0),
            end=datetime(2026, 8, 2, 23, 59, 59),
        )

    def test_today_range(self):
        result = resolve_range("today", WED)
        assert result == ResolvedRange(
            start=datetime(2026, 7, 22, 0, 0),
            end=datetime(2026, 7, 22, 23, 59, 59),
        )

    def test_unrecognized_range_phrase_returns_none(self):
        assert resolve_range("Friday", WED) is None
