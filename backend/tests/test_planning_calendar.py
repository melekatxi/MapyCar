"""Calendario laborable y capacidad diaria. Ref: 2.BE.9, RF-13, diseño §7.4.

Puro: no usa DB. Festivos de ejemplo (6 ene / 15 ago) se pasan por configuración.
"""

from __future__ import annotations

from datetime import date, time

import pytest

from app.modules.planning.calendar import (
    DEFAULT_SERVICE_MINUTES,
    DEFAULT_TIMEZONE,
    DEFAULT_WORKDAY_MINUTES,
    RURAL_TRAVEL_BUFFER_MINUTES,
    WEEKDAYS_MON_FRI,
    CalendarConstraints,
    build_monthly_calendar,
    constraints_from_json,
    daily_capacity,
)

# Agosto 2026: 1 = sábado, 15 = sábado (Asunción), 31 = lunes. 21 laborables L–V.
_AUGUST_2026_WEEKDAYS = (
    date(2026, 8, 3),
    date(2026, 8, 4),
    date(2026, 8, 5),
    date(2026, 8, 6),
    date(2026, 8, 7),
    date(2026, 8, 10),
    date(2026, 8, 11),
    date(2026, 8, 12),
    date(2026, 8, 13),
    date(2026, 8, 14),
    date(2026, 8, 17),
    date(2026, 8, 18),
    date(2026, 8, 19),
    date(2026, 8, 20),
    date(2026, 8, 21),
    date(2026, 8, 24),
    date(2026, 8, 25),
    date(2026, 8, 26),
    date(2026, 8, 27),
    date(2026, 8, 28),
    date(2026, 8, 31),
)
_EPIPHANY = date(2026, 1, 6)
_ASSUMPTION = date(2026, 8, 15)


def test_august_2026_excludes_weekends() -> None:
    calendar_ = build_monthly_calendar("2026-08")
    working = [day.date for day in calendar_.working_days]
    assert working == list(_AUGUST_2026_WEEKDAYS)
    assert all(day.isoweekday() in WEEKDAYS_MON_FRI for day in working)
    assert date(2026, 8, 1) not in working  # sábado
    assert date(2026, 8, 2) not in working  # domingo
    assert date(2026, 8, 15) not in working  # sábado
    assert date(2026, 8, 30) not in working  # domingo
    assert calendar_.timezone == DEFAULT_TIMEZONE
    assert len(working) == 21


def test_configured_holiday_is_not_a_working_day() -> None:
    january = build_monthly_calendar(
        "2026-01",
        CalendarConstraints(holidays=frozenset({date(2026, 1, 1), _EPIPHANY})),
    )
    working = {day.date for day in january.working_days}
    assert _EPIPHANY not in working
    assert date(2026, 1, 1) not in working
    assert january.skipped_holidays == (date(2026, 1, 1), _EPIPHANY)
    # 6 enero 2026 es martes: sin festivo habría sido laborable.
    assert _EPIPHANY.isoweekday() == 2

    august = build_monthly_calendar(
        "2026-08",
        holidays=[_ASSUMPTION, date(2026, 8, 14)],
    )
    working_aug = {day.date for day in august.working_days}
    assert _ASSUMPTION not in working_aug
    assert date(2026, 8, 14) not in working_aug  # viernes festivo configurado
    assert date(2026, 8, 13) in working_aug
    assert august.skipped_holidays == (date(2026, 8, 14), _ASSUMPTION)


def test_capacity_respects_workday_service_math_and_max_visits() -> None:
    # 8 h / 45 min = 10 visitas.
    unconstrained = daily_capacity(
        CalendarConstraints(
            workday_minutes=DEFAULT_WORKDAY_MINUTES,
            service_minutes=DEFAULT_SERVICE_MINUTES,
        )
    )
    assert unconstrained == (10, 480)

    capped = daily_capacity(
        CalendarConstraints(workday_minutes=480, service_minutes=45, max_visits=6)
    )
    assert capped == (6, 480)

    calendar_ = build_monthly_calendar(
        "2026-08",
        workday_minutes=480,
        service_minutes=45,
        max_visits=6,
    )
    assert calendar_.working_days
    assert all(day.capacity_visits == 6 for day in calendar_.working_days)
    assert all(day.capacity_minutes == 480 for day in calendar_.working_days)
    assert all(day.zone_kind == "urban" for day in calendar_.working_days)


def test_rural_capacity_is_lower_than_urban_with_same_jornada() -> None:
    urban = daily_capacity(
        CalendarConstraints(zone_kind="urban", workday_minutes=480, service_minutes=45)
    )
    rural = daily_capacity(
        CalendarConstraints(zone_kind="rural", workday_minutes=480, service_minutes=45)
    )
    assert urban == (10, 480)
    # Rural: 45 + 15 min de buffer de desplazamiento = 60 → 8 visitas.
    assert rural == (8, 480)
    assert RURAL_TRAVEL_BUFFER_MINUTES == 15
    assert urban[0] > rural[0]
    assert urban[1] == rural[1]

    rural_month = build_monthly_calendar("2026-08", zone_kind="rural")
    assert rural_month.working_days[0].capacity_visits == 8
    assert rural_month.working_days[0].zone_kind == "rural"


def test_window_clips_effective_workday() -> None:
    # 08:00–14:00 = 360 min → 8 visitas a 45 min, por debajo del tope 12.
    visits, minutes = daily_capacity(
        CalendarConstraints(
            workday_minutes=480,
            service_minutes=45,
            max_visits=12,
            window_start=time(8, 0),
            window_end=time(14, 0),
        ),
        on=date(2026, 8, 3),
    )
    assert minutes == 360
    assert visits == 8

    # Ventana más larga que la jornada: gana workday_minutes.
    long_window = daily_capacity(
        CalendarConstraints(
            workday_minutes=480,
            service_minutes=45,
            window_start=time(8, 0),
            window_end=time(18, 0),
        )
    )
    assert long_window == (10, 480)


def test_empty_month_when_all_weekdays_are_holidays() -> None:
    holidays = _AUGUST_2026_WEEKDAYS
    calendar_ = build_monthly_calendar("2026-08", holidays=holidays)
    assert calendar_.working_days == ()
    assert calendar_.skipped_holidays == holidays

    none = build_monthly_calendar("2026-08", weekday_mask=())
    assert none.working_days == ()
    assert none.skipped_holidays == ()


def test_extra_off_days_skip_without_counting_as_holidays() -> None:
    calendar_ = build_monthly_calendar(
        "2026-08",
        holidays=[_ASSUMPTION],
        extra_off_days=[date(2026, 8, 3)],
    )
    working = {day.date for day in calendar_.working_days}
    assert date(2026, 8, 3) not in working
    assert calendar_.skipped_holidays == (_ASSUMPTION,)


def test_constraints_json_roundtrip_is_the_monthly_plan_shape() -> None:
    payload = {
        "timezone": "Europe/Madrid",
        "weekday_mask": [1, 2, 3, 4, 5],
        "holidays": ["2026-01-06", "2026-08-15"],
        "extra_off_days": ["2026-08-14"],
        "workday_minutes": 480,
        "service_minutes": 45,
        "max_visits": 12,
        "zone_kind": "rural",
        "window_start": "08:00",
        "window_end": "16:00",
    }
    parsed = constraints_from_json(payload)
    assert parsed.to_json()["holidays"] == ["2026-01-06", "2026-08-15"]
    calendar_ = build_monthly_calendar("2026-08", payload)
    working = {day.date for day in calendar_.working_days}
    assert date(2026, 8, 14) not in working
    assert date(2026, 8, 15) not in working
    assert calendar_.working_days[0].window_start == time(8, 0)
    assert calendar_.working_days[0].window_end == time(16, 0)
    assert calendar_.working_days[0].zone_kind == "rural"


def test_invalid_period_and_window_are_rejected() -> None:
    with pytest.raises(ValueError, match="YYYY-MM"):
        build_monthly_calendar("2026-13")
    with pytest.raises(ValueError, match="YYYY-MM"):
        build_monthly_calendar("agosto")
    with pytest.raises(ValueError, match="window_end"):
        build_monthly_calendar(
            "2026-08",
            window_start="16:00",
            window_end="08:00",
        )
    with pytest.raises(ValueError, match="zone_kind"):
        build_monthly_calendar("2026-08", zone_kind="mixed")
