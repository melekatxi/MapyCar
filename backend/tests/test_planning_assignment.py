"""Asignación diaria. Ref: 2.BE.10, RF-13, diseño §7.4.

Cohorte de 200 pacientes ficticios (sin PII): ids P000–P199, zonas sintéticas.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, time
from random import Random

import pytest

from app.modules.planning.assignment import (
    AssignmentConflict,
    ConflictCode,
    DailyAssignmentResult,
    VisitAssignment,
    VisitRequest,
    assign_daily_visits,
    validate_daily_assignments,
)
from app.modules.planning.calendar import (
    DEFAULT_SERVICE_MINUTES,
    RURAL_TRAVEL_BUFFER_MINUTES,
    CalendarConstraints,
    MonthlyCalendar,
    WorkingDay,
    build_monthly_calendar,
)

_SEP_HOLIDAYS = (date(2026, 9, 9), date(2026, 9, 15))
_SEPTEMBER_2026 = "2026-09"
_WORK_START = time(8, 0)
_WORK_END = time(16, 0)
_COHORT_SIZE = 200
_UNCONFIRMED_TAIL = 10


def _day(
    on: date,
    *,
    visits: int = 10,
    minutes: int = 480,
    window_start: time | None = _WORK_START,
    window_end: time | None = _WORK_END,
    zone_kind: str = "urban",
) -> WorkingDay:
    return WorkingDay(
        date=on,
        capacity_visits=visits,
        capacity_minutes=minutes,
        zone_kind=zone_kind,
        window_start=window_start,
        window_end=window_end,
    )


def _visit(
    patient_id: str,
    *,
    zone_id: str = "Z-urban-0",
    kind: str = "urban",
    geocode_confirmed: bool = True,
    service_minutes: int | None = None,
    window_start: time | None = None,
    window_end: time | None = None,
) -> VisitRequest:
    return VisitRequest(
        patient_id=patient_id,
        zone_id=zone_id,
        kind=kind,
        geocode_confirmed=geocode_confirmed,
        service_minutes=service_minutes,
        window_start=window_start,
        window_end=window_end,
    )


def _fictional_cohort(n: int = _COHORT_SIZE) -> list[VisitRequest]:
    """200 puntos sintéticos: mezcla urban/rural, ventanas estrechas, 10 sin confirmar."""
    visits: list[VisitRequest] = []
    unconfirmed_from = n - _UNCONFIRMED_TAIL
    for index in range(n):
        rural = index % 5 == 1
        kind = "rural" if rural else "urban"
        zone_id = f"Z-rural-{index % 2}" if rural else f"Z-urban-{index % 6}"
        window_start = window_end = None
        if index % 10 == 3:
            window_start, window_end = time(9, 0), time(11, 0)
        elif index % 10 == 7:
            window_start, window_end = time(10, 0), time(10, 45)
        visits.append(
            _visit(
                f"P{index:03d}",
                zone_id=zone_id,
                kind=kind,
                geocode_confirmed=index < unconfirmed_from,
                window_start=window_start,
                window_end=window_end,
            )
        )
    return visits


def _september_calendar() -> MonthlyCalendar:
    return build_monthly_calendar(
        _SEPTEMBER_2026,
        CalendarConstraints(
            holidays=frozenset(_SEP_HOLIDAYS),
            workday_minutes=480,
            service_minutes=DEFAULT_SERVICE_MINUTES,
            window_start=_WORK_START,
            window_end=_WORK_END,
            zone_kind="urban",
        ),
    )


def test_200_fictional_patients_monthly_plan_has_no_assigned_conflicts() -> None:
    calendar_ = _september_calendar()
    visits = _fictional_cohort()
    assert len(visits) == 200
    assert len(calendar_.working_days) == 20
    assert calendar_.skipped_holidays == _SEP_HOLIDAYS

    result = assign_daily_visits(calendar_, visits)
    unconfirmed = {visit.patient_id for visit in visits if not visit.geocode_confirmed}
    confirmed = {visit.patient_id for visit in visits if visit.geocode_confirmed}
    assigned_ids = {item.patient_id for item in result.assignments}

    assert unconfirmed == {f"P{index:03d}" for index in range(190, 200)}
    assert unconfirmed.isdisjoint(assigned_ids)
    assert assigned_ids == confirmed
    assert {conflict.code for conflict in result.conflicts} == {ConflictCode.ADDRESS_NOT_CONFIRMED}
    assert {conflict.patient_id for conflict in result.conflicts} == unconfirmed
    assert all(conflict.patient_id not in assigned_ids for conflict in result.conflicts)

    assert validate_daily_assignments(calendar_, visits, result.assignments) == ()

    pairs = [(item.patient_id, item.date) for item in result.assignments]
    assert len(pairs) == len(set(pairs))
    assert len(assigned_ids) == len(result.assignments)

    assigned_dates = {item.date for item in result.assignments}
    assert date(2026, 9, 9) not in assigned_dates
    assert date(2026, 9, 15) not in assigned_dates
    assert all(day.isoweekday() <= 5 for day in assigned_dates)

    by_date: dict[date, list[VisitAssignment]] = defaultdict(list)
    for item in result.assignments:
        by_date[item.date].append(item)
    days = {day.date: day for day in calendar_.working_days}
    visits_by_id = {visit.patient_id: visit for visit in visits}
    for service_date, items in by_date.items():
        day = days[service_date]
        assert len(items) <= day.capacity_visits
        minutes = 0
        for item in items:
            visit = visits_by_id[item.patient_id]
            base = visit.service_minutes or DEFAULT_SERVICE_MINUTES
            minutes += base + (RURAL_TRAVEL_BUFFER_MINUTES if visit.kind == "rural" else 0)
        assert minutes <= day.capacity_minutes

    again = assign_daily_visits(calendar_, visits)
    assert again == result


def test_200_patient_assignment_is_stable_under_input_shuffle() -> None:
    calendar_ = _september_calendar()
    visits = _fictional_cohort()
    shuffled = list(visits)
    Random(0).shuffle(shuffled)
    left = assign_daily_visits(calendar_, visits)
    right = assign_daily_visits(calendar_, shuffled)
    assert left.assignments == right.assignments


def test_unconfirmed_address_is_conflict_not_assigned() -> None:
    days = [_day(date(2026, 9, 1))]
    visits = [_visit("P-open"), _visit("P-raw", geocode_confirmed=False)]
    result = assign_daily_visits(days, visits)
    assert [item.patient_id for item in result.assignments] == ["P-open"]
    assert result.conflicts == (
        AssignmentConflict(
            code=ConflictCode.ADDRESS_NOT_CONFIRMED,
            patient_id="P-raw",
            zone_id="Z-urban-0",
            detail="dirección sin geocodificación confirmada",
        ),
    )


def test_duplicate_patient_is_reported_and_not_double_assigned() -> None:
    days = [_day(date(2026, 9, 1), visits=4)]
    visits = [
        _visit("P-dup", zone_id="Z-a"),
        _visit("P-dup", zone_id="Z-b"),
        _visit("P-ok"),
    ]
    result = assign_daily_visits(days, visits)
    assert {item.patient_id for item in result.assignments} == {"P-dup", "P-ok"}
    assert len(result.assignments) == 2
    assert result.conflicts[0].code == ConflictCode.DUPLICATE_PATIENT
    assert result.conflicts[0].patient_id == "P-dup"


def test_visitor_unavailable_when_all_compatible_days_are_off() -> None:
    days = [_day(date(2026, 9, 1)), _day(date(2026, 9, 2))]
    visits = [_visit("P-off", window_start=time(9, 0), window_end=time(10, 0))]
    result = assign_daily_visits(
        days,
        visits,
        visitor_off_dates={date(2026, 9, 1), date(2026, 9, 2)},
    )
    assert result.assignments == ()
    assert result.conflicts[0].code == ConflictCode.VISITOR_UNAVAILABLE
    assert result.conflicts[0].patient_id == "P-off"


def test_visitor_off_one_day_assigns_the_other() -> None:
    days = [_day(date(2026, 9, 1)), _day(date(2026, 9, 2))]
    visits = [_visit("P-flex")]
    result = assign_daily_visits(days, visits, visitor_off_dates={date(2026, 9, 1)})
    assert result.conflicts == ()
    assert result.assignments == (
        VisitAssignment(patient_id="P-flex", date=date(2026, 9, 2), zone_id="Z-urban-0"),
    )


def test_window_outside_workday() -> None:
    days = [_day(date(2026, 9, 1))]
    visits = [_visit("P-late", window_start=time(17, 0), window_end=time(18, 0))]
    result = assign_daily_visits(days, visits)
    assert result.assignments == ()
    assert result.conflicts[0].code == ConflictCode.WINDOW_OUTSIDE_WORKDAY


def test_capacity_exceeded_when_visit_does_not_fit_an_empty_day() -> None:
    days = [_day(date(2026, 9, 1), visits=10, minutes=480)]
    visits = [_visit("P-long", service_minutes=500)]
    result = assign_daily_visits(days, visits)
    assert result.assignments == ()
    assert result.conflicts[0].code == ConflictCode.CAPACITY_EXCEEDED


def test_cannot_assign_more_than_capacity_visits_that_day() -> None:
    days = [_day(date(2026, 9, 1), visits=2)]
    visits = [_visit(f"P{index}") for index in range(3)]
    result = assign_daily_visits(days, visits)
    assert len(result.assignments) == 2
    assert len(result.conflicts) == 1
    assert result.conflicts[0].code == ConflictCode.UNSCHEDULABLE
    assert result.conflicts[0].patient_id == "P2"
    by_date = defaultdict(int)
    for item in result.assignments:
        by_date[item.date] += 1
    assert by_date[date(2026, 9, 1)] == 2
    assert by_date[date(2026, 9, 1)] <= days[0].capacity_visits


def test_rural_minutes_fill_the_day_before_visit_slots() -> None:
    days = [_day(date(2026, 9, 1), visits=10, minutes=480)]
    visits = [_visit(f"R{index}", kind="rural") for index in range(9)]
    result = assign_daily_visits(days, visits)
    # 45 + 15 = 60 min; 8 * 60 = 480. El 9.º no cabe (UNSCHEDULABLE, no CAPACITY).
    assert len(result.assignments) == 8
    assert result.conflicts[0].code == ConflictCode.UNSCHEDULABLE
    assert result.conflicts[0].patient_id == "R8"


def test_unschedulable_leftover_is_not_dropped_silently() -> None:
    calendar_ = build_monthly_calendar(
        "2026-09",
        CalendarConstraints(
            holidays=frozenset(_SEP_HOLIDAYS),
            max_visits=2,
            workday_minutes=480,
            service_minutes=45,
        ),
    )
    # 20 días * 2 = 40 huecos; 50 confirmados → 10 leftover.
    visits = [_visit(f"P{index:03d}") for index in range(50)]
    result = assign_daily_visits(calendar_, visits)
    leftover = [c for c in result.conflicts if c.code == ConflictCode.UNSCHEDULABLE]
    assert len(result.assignments) == 40
    assert len(leftover) == 10
    assigned = {item.patient_id for item in result.assignments}
    assert {c.patient_id for c in leftover}.isdisjoint(assigned)


def test_tight_window_is_assigned_before_rural() -> None:
    days = [_day(date(2026, 9, 1), visits=1)]
    visits = [
        _visit("P-rural", kind="rural", zone_id="Z-r"),
        _visit(
            "P-tight",
            kind="urban",
            zone_id="Z-u",
            window_start=time(9, 0),
            window_end=time(9, 30),
        ),
    ]
    result = assign_daily_visits(days, visits)
    assert result.assignments[0].patient_id == "P-tight"
    assert result.conflicts[0].patient_id == "P-rural"
    assert result.conflicts[0].code == ConflictCode.UNSCHEDULABLE


def test_rural_is_assigned_before_unconstrained_urban() -> None:
    days = [_day(date(2026, 9, 1), visits=1)]
    visits = [
        _visit("P-urban", kind="urban", zone_id="Z-u"),
        _visit("P-rural", kind="rural", zone_id="Z-r"),
    ]
    result = assign_daily_visits(days, visits)
    assert result.assignments[0].patient_id == "P-rural"
    assert result.conflicts[0].patient_id == "P-urban"


def test_same_zone_is_packed_on_the_same_day() -> None:
    days = [_day(date(2026, 9, 1), visits=3), _day(date(2026, 9, 2), visits=3)]
    visits = [_visit(f"A{index}", zone_id="zone-a") for index in range(3)]
    visits += [_visit(f"B{index}", zone_id="zone-b") for index in range(3)]
    result = assign_daily_visits(days, visits)
    assert result.conflicts == ()
    by_date = defaultdict(set)
    for item in result.assignments:
        by_date[item.date].add(item.zone_id)
    assert by_date[date(2026, 9, 1)] == {"zone-a"}
    assert by_date[date(2026, 9, 2)] == {"zone-b"}


def test_validate_reports_capacity_overflow_on_proposed_plan() -> None:
    days = [_day(date(2026, 9, 1), visits=2)]
    visits = [_visit(f"P{index}") for index in range(3)]
    proposed = [
        VisitAssignment(patient_id=f"P{index}", date=date(2026, 9, 1), zone_id="Z-urban-0")
        for index in range(3)
    ]
    conflicts = validate_daily_assignments(days, visits, proposed)
    assert any(item.code == ConflictCode.CAPACITY_EXCEEDED for item in conflicts)
    assert any(item.patient_id == "P2" for item in conflicts)


def test_validate_duplicate_patient_in_assignments() -> None:
    days = [_day(date(2026, 9, 1)), _day(date(2026, 9, 2))]
    visits = [_visit("P1")]
    proposed = [
        VisitAssignment(patient_id="P1", date=date(2026, 9, 1), zone_id="Z-urban-0"),
        VisitAssignment(patient_id="P1", date=date(2026, 9, 2), zone_id="Z-urban-0"),
    ]
    conflicts = validate_daily_assignments(days, visits, proposed)
    assert conflicts[0].code == ConflictCode.DUPLICATE_PATIENT


def test_invalid_visit_is_rejected() -> None:
    days = [_day(date(2026, 9, 1))]
    with pytest.raises(ValueError, match="kind"):
        assign_daily_visits(days, [_visit("P1", kind="mixed")])
    with pytest.raises(ValueError, match="window_end"):
        assign_daily_visits(
            days,
            [_visit("P1", window_start=time(16, 0), window_end=time(8, 0))],
        )


def test_empty_calendar_marks_confirmed_visits_unschedulable() -> None:
    visits = [_visit("P1"), _visit("P2", geocode_confirmed=False)]
    result = assign_daily_visits((), visits)
    codes = {c.patient_id: c.code for c in result.conflicts}
    assert result.assignments == ()
    assert codes["P1"] == ConflictCode.UNSCHEDULABLE
    assert codes["P2"] == ConflictCode.ADDRESS_NOT_CONFIRMED
    assert isinstance(result, DailyAssignmentResult)
