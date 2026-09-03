import { useCallback, useEffect, useMemo, useState, type DragEvent, type FormEvent } from "react";
import { useAuth } from "../auth/AuthContext";
import { ApiError } from "../api/client";
import { listPatients } from "../api/patients";
import {
  DEFAULT_CALENDAR_CONSTRAINTS,
  createPlan,
  generatePlan,
  getPlan,
  listPlans,
  listTeams,
  pollPlan,
} from "../api/planning";
import { listZones } from "../api/zoning";
import type {
  MonthlyPlan,
  PatientSummary,
  PlanConflict,
  PlanListItem,
  TeamSummary,
  ZoneSummary,
} from "../api/types";
import { ZoneKindBadge } from "../zoning/ZoneKindBadge";
import { applyVisitMove, dropVisitOnDay, parseDraggedVisit } from "./moveVisit";

const WEEKDAY_LABELS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"];
const STATUS_LABELS: Record<string, string> = {
  draft: "Borrador",
  published: "Publicado",
  validating: "Validando",
  archived: "Archivado",
};

function errorMessage(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.body.detail : fallback;
}

function knownKind(kind: string | undefined): string | undefined {
  if (kind === "urban" || kind === "rural" || kind === "mixed") return kind;
  return undefined;
}

function buildMonthCells(period: string): Array<{ iso: string | null; inMonth: boolean }> {
  const match = /^(\d{4})-(\d{2})$/.exec(period);
  if (!match) return [];
  const year = Number(match[1]);
  const month = Number(match[2]);
  const firstWeekday = new Date(Date.UTC(year, month - 1, 1)).getUTCDay();
  const mondayOffset = (firstWeekday + 6) % 7;
  const lastDate = new Date(Date.UTC(year, month, 0)).getUTCDate();
  const cells: Array<{ iso: string | null; inMonth: boolean }> = [];
  for (let i = 0; i < mondayOffset; i += 1) {
    cells.push({ iso: null, inMonth: false });
  }
  for (let day = 1; day <= lastDate; day += 1) {
    cells.push({
      iso: `${match[1]}-${match[2]}-${String(day).padStart(2, "0")}`,
      inMonth: true,
    });
  }
  while (cells.length % 7 !== 0) {
    cells.push({ iso: null, inMonth: false });
  }
  return cells;
}

export function PlanCalendarPage() {
  const { organizationId, user } = useAuth();
  const [teams, setTeams] = useState<TeamSummary[]>([]);
  const [planSummaries, setPlanSummaries] = useState<PlanListItem[]>([]);
  const [plan, setPlan] = useState<MonthlyPlan | null>(null);
  const [patients, setPatients] = useState<PatientSummary[]>([]);
  const [zones, setZones] = useState<ZoneSummary[]>([]);
  const [period, setPeriod] = useState("");
  const [teamId, setTeamId] = useState("");
  const [maxVisits, setMaxVisits] = useState("");
  const [workdayMinutes, setWorkdayMinutes] = useState(
    String(DEFAULT_CALENDAR_CONSTRAINTS.workday_minutes),
  );
  const [serviceMinutes, setServiceMinutes] = useState(
    String(DEFAULT_CALENDAR_CONSTRAINTS.service_minutes),
  );
  const [formPatientId, setFormPatientId] = useState("");
  const [formDate, setFormDate] = useState("");
  const [formZoneId, setFormZoneId] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [moveConflicts, setMoveConflicts] = useState<PlanConflict[]>([]);
  const [dragOverDate, setDragOverDate] = useState<string | null>(null);

  const loadCatalog = useCallback(async () => {
    if (!organizationId) return;
    const [teamResponse, planResponse, zoneResponse, patientResponse] = await Promise.all([
      listTeams(organizationId),
      listPlans(organizationId),
      listZones(organizationId),
      listPatients(organizationId),
    ]);
    setTeams(teamResponse.teams);
    setPlanSummaries(planResponse.plans);
    setZones(zoneResponse.zones);
    setPatients(patientResponse.patients);
    setTeamId((current) => current || teamResponse.teams[0]?.id || "");
  }, [organizationId]);

  useEffect(() => {
    loadCatalog().catch((err) => {
      setError(errorMessage(err, "No se pudieron cargar los planes"));
    });
  }, [loadCatalog]);

  const patientsById = useMemo(
    () => new Map(patients.map((patient) => [patient.id, patient])),
    [patients],
  );
  const zonesById = useMemo(
    () => new Map(zones.map((zone) => [zone.id, zone])),
    [zones],
  );
  const workingByDate = useMemo(() => {
    const map = new Map(plan?.calendar.working_days.map((day) => [day.date, day]) ?? []);
    return map;
  }, [plan]);
  const assignmentsByDate = useMemo(() => {
    const grouped = new Map<string, MonthlyPlan["assignments"]>();
    for (const assignment of plan?.assignments ?? []) {
      const current = grouped.get(assignment.date) ?? [];
      current.push(assignment);
      grouped.set(assignment.date, current);
    }
    return grouped;
  }, [plan]);

  const monthCells = useMemo(
    () => (plan ? buildMonthCells(plan.period) : []),
    [plan],
  );
  const canEdit = plan?.status === "draft";

  function patientLabel(patientId: string): string {
    return patientsById.get(patientId)?.display_ref ?? patientId;
  }

  function zoneLabel(zoneId: string): string {
    return zonesById.get(zoneId)?.name ?? zoneId;
  }

  function zoneKind(zoneId: string): string | undefined {
    return knownKind(zonesById.get(zoneId)?.kind);
  }

  async function openPlan(planId: string) {
    if (!organizationId) return;
    setBusy(true);
    setError(null);
    setMoveConflicts([]);
    try {
      const loaded = await getPlan(planId, organizationId);
      setPlan(loaded);
      setMessage(null);
    } catch (err) {
      setError(errorMessage(err, "No se pudo abrir el plan"));
    } finally {
      setBusy(false);
    }
  }

  async function handleCreateAndGenerate(event: FormEvent) {
    event.preventDefault();
    if (!organizationId) return;
    const parsedWorkday = Number.parseInt(workdayMinutes, 10);
    const parsedService = Number.parseInt(serviceMinutes, 10);
    if (!Number.isFinite(parsedWorkday) || parsedWorkday < 1) {
      setError("La jornada debe ser un entero mayor que 0.");
      return;
    }
    if (!Number.isFinite(parsedService) || parsedService < 1) {
      setError("La duración de servicio debe ser un entero mayor que 0.");
      return;
    }
    const constraints: Record<string, unknown> = {
      weekday_mask: [...DEFAULT_CALENDAR_CONSTRAINTS.weekday_mask],
      workday_minutes: parsedWorkday,
      service_minutes: parsedService,
      timezone: DEFAULT_CALENDAR_CONSTRAINTS.timezone,
      zone_kind: DEFAULT_CALENDAR_CONSTRAINTS.zone_kind,
    };
    const parsedMax = maxVisits.trim() ? Number.parseInt(maxVisits, 10) : undefined;
    if (parsedMax !== undefined) {
      if (!Number.isFinite(parsedMax) || parsedMax < 0) {
        setError("El máximo de visitas debe ser un entero mayor o igual que 0.");
        return;
      }
      constraints.max_visits = parsedMax;
    }
    setBusy(true);
    setError(null);
    setMoveConflicts([]);
    setMessage("Creando y generando el plan…");
    try {
      const created = await createPlan({
        organization_id: organizationId,
        team_id: teamId,
        period,
        constraints,
      });
      await generatePlan(created.id, organizationId);
      const ready = await pollPlan(created.id, organizationId);
      setPlan(ready);
      const listed = await listPlans(organizationId);
      setPlanSummaries(listed.plans);
      setMessage("Plan generado. Arrastra una visita o usa el formulario para moverla.");
    } catch (err) {
      setError(errorMessage(err, "No se pudo generar el plan"));
      setMessage(null);
    } finally {
      setBusy(false);
    }
  }

  async function handleGenerateExisting() {
    if (!organizationId || !plan) return;
    setBusy(true);
    setError(null);
    setMessage("Generando el plan…");
    try {
      await generatePlan(plan.id, organizationId);
      const ready = await pollPlan(plan.id, organizationId);
      setPlan(ready);
      setMessage("Plan generado. Arrastra una visita o usa el formulario para moverla.");
    } catch (err) {
      setError(errorMessage(err, "No se pudo generar el plan"));
      setMessage(null);
    } finally {
      setBusy(false);
    }
  }

  async function submitMove(patientId: string, date: string, zoneId: string) {
    if (!organizationId || !plan) return;
    if (!canEdit) {
      setError("Solo se pueden mover visitas en un plan borrador.");
      return;
    }
    try {
      const result = await applyVisitMove({
        organizationId,
        planId: plan.id,
        patientId,
        date,
        zoneId,
        version: plan.version,
      });
      if (!result.ok) {
        setMoveConflicts(result.conflicts);
        setError("El movimiento tiene conflictos. No se ha confirmado.");
        return;
      }
      const next = result.plan ?? (await getPlan(plan.id, organizationId));
      setPlan(next);
      setMoveConflicts([]);
      setError(null);
      setMessage("Visita movida.");
    } catch (err) {
      setError(errorMessage(err, "No se pudo mover la visita"));
    }
  }

  async function handleFormMove(event: FormEvent) {
    event.preventDefault();
    await submitMove(formPatientId, formDate, formZoneId);
  }

  function handleDragStart(
    assignment: MonthlyPlan["assignments"][number],
    event: DragEvent<HTMLElement>,
  ) {
    event.dataTransfer.setData(
      "text/plain",
      JSON.stringify({
        patientId: assignment.patient_id,
        zoneId: assignment.zone_id,
        date: assignment.date,
      }),
    );
    event.dataTransfer.effectAllowed = "move";
  }

  function handleDropOnDay(date: string, event: DragEvent<HTMLElement>) {
    event.preventDefault();
    setDragOverDate(null);
    if (!canEdit) return;
    const intent = dropVisitOnDay(parseDraggedVisit(event.dataTransfer), date);
    if (!intent) return;
    void submitMove(intent.patientId, intent.date, intent.zoneId);
  }

  const createdByNote =
    plan && user
      ? plan.created_by === user.id
        ? `Creado por ${user.display_name}`
        : `Creado por ${plan.created_by}`
      : null;
  const selectedZoneKind = zoneKind(formZoneId);

  return (
    <section className="page plan-calendar">
      <h1>Planificación</h1>
      <p>
        Crea un plan mensual, genera el calendario y mueve visitas. El arrastre y
        el formulario usan el mismo comando versionado (primero simulación, luego
        confirmación).
      </p>
      {message && (
        <p className="banner" role="status">
          {message}
        </p>
      )}
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}

      <form className="card form" onSubmit={handleCreateAndGenerate}>
        <h2>Nuevo plan</h2>
        <label htmlFor="plan-period">Periodo (AAAA-MM)</label>
        <input
          id="plan-period"
          type="month"
          required
          value={period}
          onChange={(event) => setPeriod(event.target.value)}
        />
        <label htmlFor="plan-team">Equipo</label>
        <select
          id="plan-team"
          required
          value={teamId}
          onChange={(event) => setTeamId(event.target.value)}
        >
          <option value="">Selecciona un equipo</option>
          {teams.map((team) => (
            <option key={team.id} value={team.id}>
              {team.name}
            </option>
          ))}
        </select>
        <label htmlFor="plan-max-visits">Máximo de visitas por día (opcional)</label>
        <input
          id="plan-max-visits"
          type="number"
          min={0}
          value={maxVisits}
          onChange={(event) => setMaxVisits(event.target.value)}
        />
        <label htmlFor="plan-workday">Jornada (minutos)</label>
        <input
          id="plan-workday"
          type="number"
          min={1}
          required
          value={workdayMinutes}
          onChange={(event) => setWorkdayMinutes(event.target.value)}
        />
        <label htmlFor="plan-service">Duración de servicio (minutos)</label>
        <input
          id="plan-service"
          type="number"
          min={1}
          required
          value={serviceMinutes}
          onChange={(event) => setServiceMinutes(event.target.value)}
        />
        <p className="plan-calendar__hint">
          Días laborables L–V, zona horaria Europe/Madrid.
        </p>
        <button type="submit" disabled={busy || !organizationId}>
          {busy ? "Generando…" : "Crear y generar"}
        </button>
      </form>

      {planSummaries.length > 0 && (
        <section className="card">
          <h2>Planes</h2>
          <ul className="plan-calendar__plans" aria-label="Planes de la organización">
            {planSummaries.map((item) => (
              <li key={item.id}>
                <span>
                  {item.period} · {STATUS_LABELS[item.status] ?? item.status}
                </span>
                <button
                  type="button"
                  data-testid={`plan-open-${item.id}`}
                  onClick={() => void openPlan(item.id)}
                  disabled={busy}
                >
                  Abrir
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      {plan && (
        <section className="card">
          <h2>
            Calendario {plan.period} · {STATUS_LABELS[plan.status] ?? plan.status}
          </h2>
          <p className="plan-calendar__meta">
            {createdByNote}
            {plan.calendar.timezone ? ` · ${plan.calendar.timezone}` : ""}
            {` · ${plan.metrics.n_assigned} visitas`}
          </p>
          <p className="plan-calendar__assignee">Visitador: Sin asignar</p>
          {plan.assignments.length === 0 && canEdit && (
            <button type="button" onClick={() => void handleGenerateExisting()} disabled={busy}>
              Generar plan
            </button>
          )}

          {plan.conflicts.length > 0 && (
            <div className="plan-calendar__conflicts">
              <h3>Conflictos del plan</h3>
              <ul data-testid="plan-conflicts" aria-label="Conflictos del plan">
                {plan.conflicts.map((conflict, index) => (
                  <li key={`${conflict.code}-${conflict.patient_id}-${index}`}>
                    {conflict.code}
                    {conflict.detail ? `: ${conflict.detail}` : ""}
                    {` · ${patientLabel(conflict.patient_id)}`}
                    {conflict.date ? ` · ${conflict.date}` : ""}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {moveConflicts.length > 0 && (
            <div className="plan-calendar__conflicts" role="alert">
              <h3>Conflictos del movimiento</h3>
              <ul data-testid="move-conflicts" aria-label="Conflictos del movimiento">
                {moveConflicts.map((conflict, index) => (
                  <li key={`${conflict.code}-${conflict.patient_id}-${index}`}>
                    {conflict.code}
                    {conflict.detail ? `: ${conflict.detail}` : ""}
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="plan-calendar__month">
            <div className="plan-calendar__grid" role="grid" aria-label="Calendario mensual">
              {WEEKDAY_LABELS.map((label) => (
                <div key={label} className="plan-calendar__weekday" role="columnheader">
                  {label}
                </div>
              ))}
              {monthCells.map((cell, index) => {
                if (!cell.iso || !cell.inMonth) {
                  return (
                    <div
                      key={`pad-${index}`}
                      className="plan-calendar__day plan-calendar__day--muted"
                    />
                  );
                }
                const working = workingByDate.get(cell.iso);
                if (!working) {
                  return (
                    <div
                      key={cell.iso}
                      className="plan-calendar__day plan-calendar__day--muted"
                      data-testid={`plan-day-${cell.iso}`}
                    >
                      <p className="plan-calendar__date">{Number(cell.iso.slice(-2))}</p>
                    </div>
                  );
                }
                const visits = assignmentsByDate.get(cell.iso) ?? [];
                const capacityText = `${visits.length} / ${working.capacity_visits}`;
                const full = visits.length >= working.capacity_visits;
                return (
                  <div
                    key={cell.iso}
                    className={`plan-calendar__day ${full ? "plan-calendar__day--full" : ""} ${
                      dragOverDate === cell.iso ? "plan-calendar__day--over" : ""
                    }`}
                    data-testid={`plan-day-${cell.iso}`}
                    onDragOver={(event) => {
                      if (!canEdit) return;
                      event.preventDefault();
                      setDragOverDate(cell.iso);
                    }}
                    onDragLeave={() => setDragOverDate(null)}
                    onDrop={(event) => handleDropOnDay(cell.iso, event)}
                    aria-label={`Día ${cell.iso}, capacidad ${capacityText}`}
                  >
                    <p className="plan-calendar__date">{Number(cell.iso.slice(-2))}</p>
                    {knownKind(working.zone_kind) ? (
                      <ZoneKindBadge kind={working.zone_kind} />
                    ) : null}
                    <p
                      className="plan-calendar__capacity"
                      data-testid={`plan-capacity-${cell.iso}`}
                    >
                      Capacidad: {capacityText}
                    </p>
                    <p className="plan-calendar__assignee">Sin asignar</p>
                    <ul className="plan-calendar__chips" aria-label={`Visitas del ${cell.iso}`}>
                      {visits.map((assignment) => {
                        const kind = zoneKind(assignment.zone_id);
                        return (
                          <li
                            key={assignment.patient_id}
                            className="plan-calendar__chip"
                            draggable={canEdit}
                            data-testid={`plan-visit-${assignment.patient_id}`}
                            onDragStart={(event) => handleDragStart(assignment, event)}
                          >
                            {patientLabel(assignment.patient_id)}
                            <span className="plan-calendar__chip-zone">
                              {zoneLabel(assignment.zone_id)}
                              {kind ? <ZoneKindBadge kind={kind} /> : null}
                            </span>
                          </li>
                        );
                      })}
                    </ul>
                  </div>
                );
              })}
            </div>
          </div>

          {canEdit && (
            <form className="form plan-calendar__form" onSubmit={handleFormMove}>
              <h3>Mover visita</h3>
              <p className="plan-calendar__hint">
                Alternativa accesible al arrastre: elige paciente, fecha y zona.
              </p>
              <label htmlFor="move-patient">Paciente</label>
              <select
                id="move-patient"
                required
                value={formPatientId}
                onChange={(event) => {
                  const nextId = event.target.value;
                  setFormPatientId(nextId);
                  const current = plan.assignments.find((item) => item.patient_id === nextId);
                  if (current) {
                    setFormDate(current.date);
                    setFormZoneId(current.zone_id);
                  }
                }}
              >
                <option value="">Selecciona un paciente</option>
                {plan.assignments.map((assignment) => (
                  <option key={assignment.patient_id} value={assignment.patient_id}>
                    {patientLabel(assignment.patient_id)}
                  </option>
                ))}
              </select>
              <label htmlFor="move-date">Fecha</label>
              <select
                id="move-date"
                required
                value={formDate}
                onChange={(event) => setFormDate(event.target.value)}
              >
                <option value="">Selecciona un día</option>
                {plan.calendar.working_days.map((day) => (
                  <option key={day.date} value={day.date}>
                    {day.date}
                  </option>
                ))}
              </select>
              <label htmlFor="move-zone">Zona</label>
              <select
                id="move-zone"
                required
                value={formZoneId}
                onChange={(event) => setFormZoneId(event.target.value)}
              >
                <option value="">Selecciona una zona</option>
                {zones.map((zone) => (
                  <option key={zone.id} value={zone.id}>
                    {zone.name}
                  </option>
                ))}
              </select>
              {selectedZoneKind ? (
                <p className="plan-calendar__hint">
                  <span>{zoneLabel(formZoneId)}</span>
                  <ZoneKindBadge kind={selectedZoneKind} />
                </p>
              ) : null}
              <button type="submit" disabled={busy}>
                Mover visita
              </button>
            </form>
          )}
        </section>
      )}
    </section>
  );
}
