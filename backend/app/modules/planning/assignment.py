"""Asignación diaria de visitas. Ref: RF-13, diseño §7.4.

Puro: no toca DB ni HTTP (persistir/publicar es 2.BE.11–12). Recibe los días
laborables de `calendar.build_monthly_calendar` y una lista de visitas.

Prioridad de asignación (clave de orden, menor primero):

1. `window_minutes` — duración de la ventana del paciente en minutos. Sin
   ventana → +inf (se empaquetan al final).
2. `rural_rank` — 0 rural, 1 urban. Tras ventanas estrechas, las rurales van
   antes: consumen más minutos (`RURAL_TRAVEL_BUFFER_MINUTES`).
3. `zone_id` — agrupa la misma zona de forma estable.
4. `patient_id` — desempate determinista. Sin RNG.

Elección de día (menor primero), una vez filtrados los laborables compatibles:

1. `zone_affinity` — 0 el día ya sirve esta zona; 1 día vacío; 2 otras zonas.
   Minimiza cambios de zona por día.
2. `pack_or_balance` — si affinity 0, `remaining_visits` (llenar el día de esa
   zona). Si no, visitas ya asignadas ese día (balancear carga sobre vacíos).
3. `date` — cronológico.

Conflictos (un visitante no asignado, nunca silencioso):

- ADDRESS_NOT_CONFIRMED — `geocode_confirmed=False`; no entra al solver.
- DUPLICATE_PATIENT — mismo `patient_id` que una visita anterior de la entrada.
- WINDOW_OUTSIDE_WORKDAY — la ventana no solapa la jornada de ningún laborable.
- VISITOR_UNAVAILABLE — todos los laborables con ventana compatible están en
  `visitor_off_dates`.
- CAPACITY_EXCEEDED — ni un día compatible vacío cabe (minutos o max visitas).
- UNSCHEDULABLE — cabría en un día vacío, pero el empaquetado agotó el resto.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from enum import StrEnum
from math import inf

from app.modules.planning.calendar import (
    DEFAULT_SERVICE_MINUTES,
    RURAL_TRAVEL_BUFFER_MINUTES,
    ZONE_KIND_RURAL,
    ZONE_KIND_URBAN,
    MonthlyCalendar,
    WorkingDay,
)

DEFAULT_WORKDAY_START = time(8, 0)
_VALID_KINDS = frozenset({ZONE_KIND_URBAN, ZONE_KIND_RURAL})


class ConflictCode(StrEnum):
    DUPLICATE_PATIENT = "DUPLICATE_PATIENT"
    VISITOR_UNAVAILABLE = "VISITOR_UNAVAILABLE"
    WINDOW_OUTSIDE_WORKDAY = "WINDOW_OUTSIDE_WORKDAY"
    CAPACITY_EXCEEDED = "CAPACITY_EXCEEDED"
    ADDRESS_NOT_CONFIRMED = "ADDRESS_NOT_CONFIRMED"
    UNSCHEDULABLE = "UNSCHEDULABLE"


@dataclass(frozen=True)
class VisitRequest:
    """Visita a colocar. `service_minutes` es atención; rural suma el buffer."""

    patient_id: str
    zone_id: str
    kind: str
    geocode_confirmed: bool = True
    service_minutes: int | None = None
    window_start: time | None = None
    window_end: time | None = None


@dataclass(frozen=True)
class VisitAssignment:
    patient_id: str
    date: date
    zone_id: str


@dataclass(frozen=True)
class AssignmentConflict:
    code: ConflictCode
    patient_id: str
    date: date | None = None
    zone_id: str | None = None
    detail: str = ""


@dataclass(frozen=True)
class DailyAssignmentResult:
    assignments: tuple[VisitAssignment, ...]
    conflicts: tuple[AssignmentConflict, ...]


@dataclass
class _DayState:
    day: WorkingDay
    remaining_visits: int
    remaining_minutes: int
    zone_ids: list[str] = field(default_factory=list)

    @property
    def assigned_count(self) -> int:
        return self.day.capacity_visits - self.remaining_visits


def assign_daily_visits(
    working_days: MonthlyCalendar | Sequence[WorkingDay],
    visits: Sequence[VisitRequest],
    *,
    visitor_off_dates: Iterable[date] = (),
    default_service_minutes: int = DEFAULT_SERVICE_MINUTES,
) -> DailyAssignmentResult:
    """Propone un plan diario. No persiste. Determinista para la misma entrada."""
    if default_service_minutes <= 0:
        raise ValueError("default_service_minutes debe ser > 0")

    days = _as_working_days(working_days)
    off = frozenset(visitor_off_dates)
    states = [
        _DayState(
            day=day,
            remaining_visits=day.capacity_visits,
            remaining_minutes=day.capacity_minutes,
        )
        for day in days
    ]

    conflicts: list[AssignmentConflict] = []
    candidates: list[VisitRequest] = []
    seen: set[str] = set()
    for visit in visits:
        _validate_visit(visit)
        if not visit.geocode_confirmed:
            conflicts.append(
                AssignmentConflict(
                    code=ConflictCode.ADDRESS_NOT_CONFIRMED,
                    patient_id=visit.patient_id,
                    zone_id=visit.zone_id,
                    detail="dirección sin geocodificación confirmada",
                )
            )
            seen.add(visit.patient_id)
            continue
        if visit.patient_id in seen:
            conflicts.append(
                AssignmentConflict(
                    code=ConflictCode.DUPLICATE_PATIENT,
                    patient_id=visit.patient_id,
                    zone_id=visit.zone_id,
                    detail="paciente duplicado en la entrada",
                )
            )
            continue
        seen.add(visit.patient_id)
        candidates.append(visit)

    candidates.sort(key=_priority_key)

    assignments: list[VisitAssignment] = []
    for visit in candidates:
        placed = _place_visit(
            visit,
            states,
            off=off,
            default_service_minutes=default_service_minutes,
        )
        if isinstance(placed, AssignmentConflict):
            conflicts.append(placed)
            continue
        assignments.append(
            VisitAssignment(
                patient_id=visit.patient_id,
                date=placed.date,
                zone_id=visit.zone_id,
            )
        )

    assignments.sort(key=lambda item: (item.date, item.zone_id, item.patient_id))
    return DailyAssignmentResult(tuple(assignments), tuple(conflicts))


def validate_daily_assignments(
    working_days: MonthlyCalendar | Sequence[WorkingDay],
    visits: Sequence[VisitRequest],
    assignments: Sequence[VisitAssignment],
    *,
    visitor_off_dates: Iterable[date] = (),
    default_service_minutes: int = DEFAULT_SERVICE_MINUTES,
) -> tuple[AssignmentConflict, ...]:
    """Conflictos de un plan ya propuesto. No muta. Útil para 2.BE.11 validate."""
    if default_service_minutes <= 0:
        raise ValueError("default_service_minutes debe ser > 0")

    days_by_date = {day.date: day for day in _as_working_days(working_days)}
    off = frozenset(visitor_off_dates)
    visits_by_id: dict[str, VisitRequest] = {}
    for visit in visits:
        _validate_visit(visit)
        visits_by_id.setdefault(visit.patient_id, visit)

    conflicts: list[AssignmentConflict] = []
    seen_patients: set[str] = set()
    by_date: dict[date, list[VisitAssignment]] = {}
    for item in assignments:
        if item.patient_id in seen_patients:
            conflicts.append(
                AssignmentConflict(
                    code=ConflictCode.DUPLICATE_PATIENT,
                    patient_id=item.patient_id,
                    date=item.date,
                    zone_id=item.zone_id,
                    detail="paciente asignado más de una vez",
                )
            )
            continue
        seen_patients.add(item.patient_id)
        by_date.setdefault(item.date, []).append(item)

    for service_date, day_items in sorted(by_date.items()):
        day = days_by_date.get(service_date)
        ordered = sorted(day_items, key=lambda item: (item.zone_id, item.patient_id))
        if day is None:
            for item in ordered:
                conflicts.append(
                    AssignmentConflict(
                        code=ConflictCode.WINDOW_OUTSIDE_WORKDAY,
                        patient_id=item.patient_id,
                        date=item.date,
                        zone_id=item.zone_id,
                        detail="fecha fuera del calendario laborable",
                    )
                )
            continue
        remaining_visits = day.capacity_visits
        remaining_minutes = day.capacity_minutes
        for item in ordered:
            visit = visits_by_id.get(item.patient_id)
            if visit is None:
                conflicts.append(
                    AssignmentConflict(
                        code=ConflictCode.UNSCHEDULABLE,
                        patient_id=item.patient_id,
                        date=item.date,
                        zone_id=item.zone_id,
                        detail="visita ausente de la entrada",
                    )
                )
                continue
            if not visit.geocode_confirmed:
                conflicts.append(
                    AssignmentConflict(
                        code=ConflictCode.ADDRESS_NOT_CONFIRMED,
                        patient_id=item.patient_id,
                        date=item.date,
                        zone_id=item.zone_id,
                    )
                )
                continue
            if service_date in off:
                conflicts.append(
                    AssignmentConflict(
                        code=ConflictCode.VISITOR_UNAVAILABLE,
                        patient_id=item.patient_id,
                        date=item.date,
                        zone_id=item.zone_id,
                    )
                )
                continue
            if not _window_compatible(visit, day):
                conflicts.append(
                    AssignmentConflict(
                        code=ConflictCode.WINDOW_OUTSIDE_WORKDAY,
                        patient_id=item.patient_id,
                        date=item.date,
                        zone_id=item.zone_id,
                    )
                )
                continue
            service = _visit_service_minutes(visit, default_service_minutes)
            if remaining_visits < 1 or remaining_minutes < service:
                conflicts.append(
                    AssignmentConflict(
                        code=ConflictCode.CAPACITY_EXCEEDED,
                        patient_id=item.patient_id,
                        date=item.date,
                        zone_id=item.zone_id,
                        detail="excede capacity_visits o capacity_minutes del día",
                    )
                )
                continue
            remaining_visits -= 1
            remaining_minutes -= service

    return tuple(conflicts)


def _place_visit(
    visit: VisitRequest,
    states: Sequence[_DayState],
    *,
    off: frozenset[date],
    default_service_minutes: int,
) -> WorkingDay | AssignmentConflict:
    """Coloca `visit` (muta el `_DayState` elegido) o devuelve el conflicto."""
    service = _visit_service_minutes(visit, default_service_minutes)

    if not states:
        return AssignmentConflict(
            code=ConflictCode.UNSCHEDULABLE,
            patient_id=visit.patient_id,
            zone_id=visit.zone_id,
            detail="no hay días laborables",
        )

    window_ok = [state for state in states if _window_compatible(visit, state.day)]
    if not window_ok:
        return AssignmentConflict(
            code=ConflictCode.WINDOW_OUTSIDE_WORKDAY,
            patient_id=visit.patient_id,
            zone_id=visit.zone_id,
            detail="ventana fuera de la jornada laborable",
        )

    available = [state for state in window_ok if state.day.date not in off]
    if not available:
        return AssignmentConflict(
            code=ConflictCode.VISITOR_UNAVAILABLE,
            patient_id=visit.patient_id,
            zone_id=visit.zone_id,
            detail="visitador no disponible en días compatibles",
        )

    if all(
        service > state.day.capacity_minutes or state.day.capacity_visits < 1 for state in available
    ):
        return AssignmentConflict(
            code=ConflictCode.CAPACITY_EXCEEDED,
            patient_id=visit.patient_id,
            zone_id=visit.zone_id,
            detail="la visita no cabe en la capacidad de ningún día compatible",
        )

    placeable = [
        state
        for state in available
        if state.remaining_visits >= 1 and state.remaining_minutes >= service
    ]
    if not placeable:
        return AssignmentConflict(
            code=ConflictCode.UNSCHEDULABLE,
            patient_id=visit.patient_id,
            zone_id=visit.zone_id,
            detail="sin hueco tras empaquetar el resto (capacidad)",
        )

    chosen = min(placeable, key=lambda state: _day_choice_key(state, visit.zone_id))
    chosen.remaining_visits -= 1
    chosen.remaining_minutes -= service
    chosen.zone_ids.append(visit.zone_id)
    return chosen.day


def _priority_key(visit: VisitRequest) -> tuple[float, int, str, str]:
    """Ver docstring del módulo: window_minutes, rural_rank, zone_id, patient_id."""
    if visit.window_start is None or visit.window_end is None:
        window_minutes = inf
    else:
        window_minutes = float(_clock_minutes(visit.window_start, visit.window_end))
    rural_rank = 0 if visit.kind == ZONE_KIND_RURAL else 1
    return (window_minutes, rural_rank, visit.zone_id, visit.patient_id)


def _day_choice_key(state: _DayState, zone_id: str) -> tuple[int, int, date]:
    """Ver docstring del módulo: zone_affinity, pack_or_balance, date."""
    zones = set(state.zone_ids)
    if zone_id in zones:
        affinity = 0
        pack_or_balance = state.remaining_visits
    elif not zones:
        affinity = 1
        pack_or_balance = state.assigned_count
    else:
        affinity = 2
        pack_or_balance = state.assigned_count
    return (affinity, pack_or_balance, state.day.date)


def _visit_service_minutes(visit: VisitRequest, default_service_minutes: int) -> int:
    base = default_service_minutes if visit.service_minutes is None else visit.service_minutes
    if visit.kind == ZONE_KIND_RURAL:
        return base + RURAL_TRAVEL_BUFFER_MINUTES
    return base


def _window_compatible(visit: VisitRequest, day: WorkingDay) -> bool:
    if visit.window_start is None or visit.window_end is None:
        return True
    day_start, day_end = _day_jornada(day)
    return visit.window_start < day_end and day_start < visit.window_end


def _day_jornada(day: WorkingDay) -> tuple[time, time]:
    if day.window_start is not None and day.window_end is not None:
        return day.window_start, day.window_end
    return DEFAULT_WORKDAY_START, _add_minutes(DEFAULT_WORKDAY_START, day.capacity_minutes)


def _add_minutes(start: time, minutes: int) -> time:
    dt = datetime.combine(date(2000, 1, 1), start) + timedelta(minutes=max(minutes, 0))
    if dt.date() != date(2000, 1, 1):
        return time(23, 59)
    return dt.time()


def _clock_minutes(start: time, end: time) -> int:
    delta = datetime.combine(date.min, end) - datetime.combine(date.min, start)
    return int(delta.total_seconds() // 60)


def _as_working_days(
    source: MonthlyCalendar | Sequence[WorkingDay],
) -> tuple[WorkingDay, ...]:
    if isinstance(source, MonthlyCalendar):
        days = source.working_days
    else:
        days = tuple(source)
    return tuple(sorted(days, key=lambda day: day.date))


def _validate_visit(visit: VisitRequest) -> None:
    if not visit.patient_id:
        raise ValueError("patient_id no puede estar vacío")
    if not visit.zone_id:
        raise ValueError("zone_id no puede estar vacío")
    if visit.kind not in _VALID_KINDS:
        raise ValueError("kind debe ser 'urban' o 'rural'")
    if visit.service_minutes is not None and visit.service_minutes <= 0:
        raise ValueError("service_minutes debe ser > 0")
    start, end = visit.window_start, visit.window_end
    if (start is None) != (end is None):
        raise ValueError("window_start y window_end deben ir juntos")
    if start is not None and end is not None and end <= start:
        raise ValueError("window_end debe ser posterior a window_start (sin jornada nocturna)")
