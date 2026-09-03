"""Calendario laborable y capacidad diaria. Ref: RF-13, diseño §7.4.

Puro: no toca DB ni asigna pacientes (eso es 2.BE.10). Los festivos se reciben
como configuración; no se hardcodea el calendario oficial español. El shape de
`MonthlyPlan.constraints_json` es `CalendarConstraints.to_json()`.

Zona horaria de producto: Europe/Madrid (Bizkaia). Las fechas de visita son
civiles en esa zona; `zoneinfo` se usa para la duración de ventanas (DST).

Regla rural: se suma `RURAL_TRAVEL_BUFFER_MINUTES` a `service_minutes` antes
del floor. Modela el extra de desplazamiento entre caseríos; la jornada civil
no se acorta. Urbana usa `service_minutes` tal cual.

    capacity_visits = min(max_visits, floor(capacity_minutes / effective_service))
    capacity_minutes = min(workday_minutes, minutos de ventana ese día)
"""

from __future__ import annotations

import calendar
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, time
from math import floor
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TIMEZONE = "Europe/Madrid"
# ISO-8601: 1=lunes … 7=domingo. Producto: jornada L–V.
WEEKDAYS_MON_FRI: tuple[int, ...] = (1, 2, 3, 4, 5)
DEFAULT_WORKDAY_MINUTES = 480  # 8 h
DEFAULT_SERVICE_MINUTES = 45
# Extra por visita en zona rural (desplazamiento entre paradas, no recorte de jornada).
RURAL_TRAVEL_BUFFER_MINUTES = 15
ZONE_KIND_URBAN = "urban"
ZONE_KIND_RURAL = "rural"
_VALID_ZONE_KINDS = frozenset({ZONE_KIND_URBAN, ZONE_KIND_RURAL})
_PERIOD_LEN = 7  # YYYY-MM
_ISO_WEEKDAYS = frozenset(range(1, 8))


@dataclass(frozen=True)
class CalendarConstraints:
    """Restricciones persistidas en `monthly_plans.constraints_json` (2.BE.9)."""

    weekday_mask: frozenset[int] = frozenset(WEEKDAYS_MON_FRI)
    holidays: frozenset[date] = frozenset()
    extra_off_days: frozenset[date] = frozenset()
    workday_minutes: int = DEFAULT_WORKDAY_MINUTES
    service_minutes: int = DEFAULT_SERVICE_MINUTES
    max_visits: int | None = None
    zone_kind: str = ZONE_KIND_URBAN
    window_start: time | None = None
    window_end: time | None = None
    timezone: str = DEFAULT_TIMEZONE

    def to_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "timezone": self.timezone,
            "weekday_mask": sorted(self.weekday_mask),
            "holidays": [d.isoformat() for d in sorted(self.holidays)],
            "extra_off_days": [d.isoformat() for d in sorted(self.extra_off_days)],
            "workday_minutes": self.workday_minutes,
            "service_minutes": self.service_minutes,
            "zone_kind": self.zone_kind,
        }
        if self.max_visits is not None:
            payload["max_visits"] = self.max_visits
        if self.window_start is not None:
            payload["window_start"] = self.window_start.strftime("%H:%M")
        if self.window_end is not None:
            payload["window_end"] = self.window_end.strftime("%H:%M")
        return payload


@dataclass(frozen=True)
class WorkingDay:
    date: date
    capacity_visits: int
    capacity_minutes: int
    zone_kind: str
    window_start: time | None
    window_end: time | None


@dataclass(frozen=True)
class MonthlyCalendar:
    period: str
    timezone: str
    working_days: tuple[WorkingDay, ...]
    skipped_holidays: tuple[date, ...]


def constraints_from_json(payload: Mapping[str, Any] | None) -> CalendarConstraints:
    """Parsea `constraints_json`. Claves ausentes → defaults de producto."""
    raw = dict(payload or {})
    weekday_mask = _parse_weekday_mask(raw.get("weekday_mask", WEEKDAYS_MON_FRI))
    holidays = _parse_dates(raw.get("holidays", ()))
    extra_off_days = _parse_dates(raw.get("extra_off_days", ()))
    window_start = _parse_clock(raw.get("window_start"))
    window_end = _parse_clock(raw.get("window_end"))
    max_visits = raw.get("max_visits")
    return CalendarConstraints(
        weekday_mask=weekday_mask,
        holidays=holidays,
        extra_off_days=extra_off_days,
        workday_minutes=_parse_positive_int(
            raw.get("workday_minutes", DEFAULT_WORKDAY_MINUTES), "workday_minutes"
        ),
        service_minutes=_parse_positive_int(
            raw.get("service_minutes", DEFAULT_SERVICE_MINUTES), "service_minutes"
        ),
        max_visits=None
        if max_visits is None
        else _parse_non_negative_int(max_visits, "max_visits"),
        zone_kind=_parse_zone_kind(raw.get("zone_kind", ZONE_KIND_URBAN)),
        window_start=window_start,
        window_end=window_end,
        timezone=_parse_timezone(raw.get("timezone", DEFAULT_TIMEZONE)),
    )


def daily_capacity(
    constraints: CalendarConstraints,
    *,
    on: date | None = None,
) -> tuple[int, int]:
    """Devuelve `(capacity_visits, capacity_minutes)` para un día concreto.

    `on` solo afecta a la duración de la ventana bajo DST. Sin ventana, el día
    no influye. No asigna pacientes.
    """
    _validate_constraints(constraints)
    tz = ZoneInfo(constraints.timezone)
    capacity_minutes = _capacity_minutes(constraints, on=on, tz=tz)
    service = _effective_service_minutes(constraints)
    from_time = floor(capacity_minutes / service) if service > 0 else 0
    if constraints.max_visits is None:
        visits = from_time
    else:
        visits = min(constraints.max_visits, from_time)
    return max(visits, 0), capacity_minutes


def build_monthly_calendar(
    period: str,
    constraints: CalendarConstraints | Mapping[str, Any] | None = None,
    /,
    **overrides: Any,
) -> MonthlyCalendar:
    """Genera los días laborables de `YYYY-MM` y su capacidad, sin asignar visitas."""
    year, month = _parse_period(period)
    parsed = (
        constraints
        if isinstance(constraints, CalendarConstraints)
        else constraints_from_json(constraints)
    )
    if overrides:
        parsed = _apply_overrides(parsed, overrides)
    _validate_constraints(parsed)

    last_day = calendar.monthrange(year, month)[1]
    month_dates = [date(year, month, day) for day in range(1, last_day + 1)]
    holidays_in_month = tuple(
        sorted(d for d in parsed.holidays if d.year == year and d.month == month)
    )
    off = parsed.holidays | parsed.extra_off_days

    visits, minutes = daily_capacity(parsed, on=date(year, month, 1))
    # Recalcular por día solo si hay ventana (DST puede cambiar los minutos).
    per_day = parsed.window_start is not None

    working: list[WorkingDay] = []
    for day in month_dates:
        if day.isoweekday() not in parsed.weekday_mask:
            continue
        if day in off:
            continue
        if per_day:
            visits, minutes = daily_capacity(parsed, on=day)
        working.append(
            WorkingDay(
                date=day,
                capacity_visits=visits,
                capacity_minutes=minutes,
                zone_kind=parsed.zone_kind,
                window_start=parsed.window_start,
                window_end=parsed.window_end,
            )
        )

    return MonthlyCalendar(
        period=period,
        timezone=parsed.timezone,
        working_days=tuple(working),
        skipped_holidays=holidays_in_month,
    )


def _apply_overrides(
    base: CalendarConstraints, overrides: Mapping[str, Any]
) -> CalendarConstraints:
    payload = base.to_json()
    payload.update(overrides)
    return constraints_from_json(payload)


def _effective_service_minutes(constraints: CalendarConstraints) -> int:
    if constraints.zone_kind == ZONE_KIND_RURAL:
        return constraints.service_minutes + RURAL_TRAVEL_BUFFER_MINUTES
    return constraints.service_minutes


def _capacity_minutes(constraints: CalendarConstraints, *, on: date | None, tz: ZoneInfo) -> int:
    workday = constraints.workday_minutes
    if constraints.window_start is None or constraints.window_end is None:
        return workday
    day = on or date(2000, 1, 1)
    start_dt = datetime.combine(day, constraints.window_start, tzinfo=tz)
    end_dt = datetime.combine(day, constraints.window_end, tzinfo=tz)
    window = int((end_dt - start_dt).total_seconds() // 60)
    return min(workday, max(window, 0))


def _validate_constraints(constraints: CalendarConstraints) -> None:
    if not constraints.weekday_mask <= _ISO_WEEKDAYS:
        raise ValueError("weekday_mask debe usar ISO 1=lunes … 7=domingo")
    if constraints.workday_minutes <= 0:
        raise ValueError("workday_minutes debe ser > 0")
    if constraints.service_minutes <= 0:
        raise ValueError("service_minutes debe ser > 0")
    if constraints.max_visits is not None and constraints.max_visits < 0:
        raise ValueError("max_visits no puede ser negativo")
    if constraints.zone_kind not in _VALID_ZONE_KINDS:
        raise ValueError("zone_kind debe ser 'urban' o 'rural'")
    start, end = constraints.window_start, constraints.window_end
    if (start is None) != (end is None):
        raise ValueError("window_start y window_end deben ir juntos")
    if start is not None and end is not None and end <= start:
        raise ValueError("window_end debe ser posterior a window_start (sin jornada nocturna)")
    _parse_timezone(constraints.timezone)


def _parse_period(period: str) -> tuple[int, int]:
    if not isinstance(period, str) or len(period) != _PERIOD_LEN or period[4] != "-":
        raise ValueError("period debe ser YYYY-MM")
    year_s, month_s = period[:4], period[5:]
    if not year_s.isdigit() or not month_s.isdigit():
        raise ValueError("period debe ser YYYY-MM")
    year, month = int(year_s), int(month_s)
    if month < 1 or month > 12:
        raise ValueError("period debe ser YYYY-MM")
    return year, month


def _parse_weekday_mask(value: object) -> frozenset[int]:
    if value is None:
        return frozenset(WEEKDAYS_MON_FRI)
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes)):
        raise TypeError("weekday_mask debe ser una secuencia de ISO weekdays")
    days = frozenset(int(item) for item in value)
    if not days <= _ISO_WEEKDAYS:
        raise ValueError("weekday_mask debe usar ISO 1=lunes … 7=domingo")
    return days


def _parse_dates(value: object) -> frozenset[date]:
    if value is None:
        return frozenset()
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes)):
        raise TypeError("holidays/extra_off_days debe ser una secuencia de fechas")
    return frozenset(_parse_one_date(item) for item in value)


def _parse_one_date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise ValueError("fecha inválida; use YYYY-MM-DD")


def _parse_clock(value: object) -> time | None:
    if value is None or value == "":
        return None
    if isinstance(value, time):
        return value.replace(tzinfo=None, microsecond=0)
    if isinstance(value, str):
        parts = value.split(":")
        if len(parts) < 2:
            raise ValueError("hora inválida; use HH:MM")
        hour, minute = int(parts[0]), int(parts[1])
        return time(hour, minute)
    raise ValueError("hora inválida; use HH:MM")


def _parse_positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} debe ser un entero")
    if value <= 0:
        raise ValueError(f"{field} debe ser > 0")
    return value


def _parse_non_negative_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} debe ser un entero")
    if value < 0:
        raise ValueError(f"{field} no puede ser negativo")
    return value


def _parse_zone_kind(value: object) -> str:
    if not isinstance(value, str) or value not in _VALID_ZONE_KINDS:
        raise ValueError("zone_kind debe ser 'urban' o 'rural'")
    return value


def _parse_timezone(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("timezone debe ser un IANA tz")
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"timezone desconocido: {value}") from exc
    return value
