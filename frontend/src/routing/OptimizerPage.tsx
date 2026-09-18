import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { useAuth } from "../auth/AuthContext";
import { ApiError } from "../api/client";
import { listPatients } from "../api/patients";
import { listPlans, listPlanRoutes } from "../api/planning";
import { listZones } from "../api/zoning";
import { getRoute, getRouteComparison, optimizeRoute, pollOptimizeJob } from "../api/routing";
import type {
  DailyRouteSummary,
  JobStatus,
  PatientSummary,
  PlanListItem,
  RouteComparison as RouteComparisonData,
  RouteDetail,
  ZoneSummary,
} from "../api/types";
import { RouteComparison } from "./RouteComparison";
import { RouteDiagnostics } from "./RouteDiagnostics";
import { RouteExport } from "./RouteExport";

const DEFAULT_ORIGIN = { lat: "43.2630", lon: "-2.9350" };
const JOB_LABELS: Record<string, string> = {
  queued: "En cola",
  running: "Optimizando…",
  succeeded: "Completada",
  failed: "Error",
  cancelled: "Cancelada",
};
const ROUTE_STATUS: Record<string, string> = {
  draft: "Borrador",
  optimizing: "Optimizando",
  ready: "Lista",
  published: "Publicada",
};
const SOLVER_LABELS: Record<string, string> = {
  feasible: "Factible",
  infeasible: "Inviable",
  pending: "Pendiente",
  running: "En curso",
  timeout: "Tiempo agotado",
  failed: "Error",
};

function errorMessage(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.body.detail : fallback;
}

function parseCoord(value: string): number | null {
  const n = Number(value.replace(",", "."));
  return Number.isFinite(n) ? n : null;
}

export function OptimizerPage() {
  const { organizationId, user } = useAuth();
  const [plans, setPlans] = useState<PlanListItem[]>([]);
  const [zones, setZones] = useState<ZoneSummary[]>([]);
  const [routes, setRoutes] = useState<DailyRouteSummary[]>([]);
  const [planId, setPlanId] = useState("");
  const [routeId, setRouteId] = useState("");
  const [objective, setObjective] = useState<"time" | "cost">("time");
  const [originLat, setOriginLat] = useState(DEFAULT_ORIGIN.lat);
  const [originLon, setOriginLon] = useState(DEFAULT_ORIGIN.lon);
  const [returnToOrigin, setReturnToOrigin] = useState(true);
  const [destLat, setDestLat] = useState(DEFAULT_ORIGIN.lat);
  const [destLon, setDestLon] = useState(DEFAULT_ORIGIN.lon);
  const [serviceMinutes, setServiceMinutes] = useState("45");
  const [workdayMinutes, setWorkdayMinutes] = useState("");
  const [costPerKm, setCostPerKm] = useState("0");
  const [costPerHour, setCostPerHour] = useState("0");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [job, setJob] = useState<JobStatus | null>(null);
  const [route, setRoute] = useState<RouteDetail | null>(null);
  const [patients, setPatients] = useState<PatientSummary[]>([]);
  const [comparison, setComparison] = useState<RouteComparisonData | null>(null);
  const [comparisonError, setComparisonError] = useState<string | null>(null);

  const role = user?.memberships.find((m) => m.organization_id === organizationId)?.role;
  const canEdit = role === "admin" || role === "planner";

  const zoneName = useCallback(
    (zoneId: string) => zones.find((z) => z.id === zoneId)?.name ?? zoneId.slice(0, 8),
    [zones],
  );

  const loadCatalog = useCallback(async () => {
    if (!organizationId) return;
    const [planResponse, zoneResponse, patientResponse] = await Promise.all([
      listPlans(organizationId),
      listZones(organizationId),
      listPatients(organizationId),
    ]);
    setPlans(planResponse.plans);
    setZones(zoneResponse.zones);
    setPatients(patientResponse.patients);
    const published = planResponse.plans.find((item) => item.status === "published");
    const nextPlan = published?.id ?? planResponse.plans[0]?.id ?? "";
    setPlanId(nextPlan);
  }, [organizationId]);

  useEffect(() => {
    loadCatalog().catch((err: unknown) => {
      setError(errorMessage(err, "No se pudieron cargar los planes"));
    });
  }, [loadCatalog]);

  useEffect(() => {
    if (!organizationId || !planId) {
      setRoutes([]);
      setRouteId("");
      return;
    }
    listPlanRoutes(planId, organizationId)
      .then((response) => {
        setRoutes(response.routes);
        setRouteId(response.routes[0]?.id ?? "");
      })
      .catch((err: unknown) => {
        setError(errorMessage(err, "No se pudieron cargar las rutas"));
      });
  }, [organizationId, planId]);

  const loadComparison = useCallback(
    async (id: string) => {
      if (!organizationId) return;
      try {
        const data = await getRouteComparison(id, organizationId);
        setComparison(data);
        setComparisonError(null);
      } catch (err) {
        setComparison(null);
        if (err instanceof ApiError && (err.code === "METRICS_STALE" || err.code === "METRICS_UNAVAILABLE")) {
          setComparisonError(err.body.detail);
        } else {
          setComparisonError(errorMessage(err, "No se pudo cargar la comparativa"));
        }
      }
    },
    [organizationId],
  );

  useEffect(() => {
    if (!organizationId || !routeId) {
      setRoute(null);
      setComparison(null);
      return;
    }
    getRoute(routeId, organizationId)
      .then((detail) => {
        setRoute(detail);
        if (detail.solver_status === "infeasible") {
          setComparison(null);
          setComparisonError(null);
          return;
        }
        return loadComparison(routeId);
      })
      .catch((err: unknown) => {
        setError(errorMessage(err, "No se pudo cargar la ruta"));
      });
  }, [organizationId, routeId, loadComparison]);

  const selectedRoute = useMemo(
    () => routes.find((item) => item.id === routeId) ?? null,
    [routes, routeId],
  );

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!organizationId || !routeId || !canEdit) return;
    const lat = parseCoord(originLat);
    const lon = parseCoord(originLon);
    if (lat === null || lon === null) {
      setError("Origen: latitud y longitud numéricas");
      return;
    }
    let destination: { lat: number; lon: number } | null = null;
    if (returnToOrigin) {
      destination = { lat, lon };
    } else {
      const dLat = parseCoord(destLat);
      const dLon = parseCoord(destLon);
      if (dLat === null || dLon === null) {
        setError("Retorno: latitud y longitud numéricas");
        return;
      }
      destination = { lat: dLat, lon: dLon };
    }
    const service = Number(serviceMinutes);
    const workday = workdayMinutes.trim() === "" ? null : Number(workdayMinutes);
    setBusy(true);
    setError(null);
    try {
      const queued = await optimizeRoute({
        routeId,
        organizationId,
        idempotencyKey: crypto.randomUUID(),
        body: {
          objective,
          origin: { lat, lon },
          destination,
          cost_per_km: objective === "cost" ? Number(costPerKm) || 0 : 0,
          cost_per_hour: objective === "cost" ? Number(costPerHour) || 0 : 0,
          service_minutes: Number.isFinite(service) ? service : 45,
          vehicle_time_capacity_seconds:
            workday !== null && Number.isFinite(workday) && workday > 0
              ? workday * 60
              : null,
        },
      });
      const finished = await pollOptimizeJob(queued.job_id, organizationId, {
        onTick: setJob,
      });
      setJob(finished);
      const detail = await getRoute(routeId, organizationId);
      setRoute(detail);
      if (detail.solver_status !== "infeasible") {
        await loadComparison(routeId);
      } else {
        setComparison(null);
      }
    } catch (err) {
      setError(errorMessage(err, "No se pudo optimizar la ruta"));
    } finally {
      setBusy(false);
    }
  }

  const jobLabel = job ? (JOB_LABELS[job.status] ?? job.status) : null;

  return (
    <section className="page optimizer">
      <h1>Optimizador de rutas</h1>
      <p>
        Elige una ruta diaria, el objetivo y el origen/retorno. El cálculo se encola y
        esta pantalla muestra el progreso hasta terminar.
      </p>

      {error ? (
        <p className="form-error" role="alert">
          {error}
        </p>
      ) : null}

      <form className="form optimizer__form" onSubmit={handleSubmit}>
        <label htmlFor="optimizer-plan">Plan</label>
        <select
          id="optimizer-plan"
          data-testid="optimizer-plan"
          value={planId}
          onChange={(event) => setPlanId(event.target.value)}
        >
          {plans.length === 0 ? <option value="">Sin planes</option> : null}
          {plans.map((item) => (
            <option key={item.id} value={item.id}>
              {item.period} ({item.status})
            </option>
          ))}
        </select>

        <label htmlFor="optimizer-route">Ruta diaria</label>
        <select
          id="optimizer-route"
          data-testid="optimizer-route"
          value={routeId}
          onChange={(event) => setRouteId(event.target.value)}
        >
          {routes.length === 0 ? (
            <option value="">Publica un plan para ver rutas</option>
          ) : null}
          {routes.map((item) => (
            <option key={item.id} value={item.id}>
              {item.service_date} · {zoneName(item.zone_id)} ·{" "}
              {ROUTE_STATUS[item.status] ?? item.status}
            </option>
          ))}
        </select>

        <label htmlFor="optimizer-objective">Objetivo</label>
        <select
          id="optimizer-objective"
          data-testid="optimizer-objective"
          value={objective}
          onChange={(event) => setObjective(event.target.value as "time" | "cost")}
        >
          <option value="time">Minimizar tiempo</option>
          <option value="cost">Minimizar coste</option>
        </select>

        <fieldset className="optimizer__coords">
          <legend>Origen</legend>
          <label htmlFor="optimizer-origin-lat">Latitud</label>
          <input
            id="optimizer-origin-lat"
            data-testid="optimizer-origin-lat"
            value={originLat}
            onChange={(event) => setOriginLat(event.target.value)}
            inputMode="decimal"
            required
          />
          <label htmlFor="optimizer-origin-lon">Longitud</label>
          <input
            id="optimizer-origin-lon"
            data-testid="optimizer-origin-lon"
            value={originLon}
            onChange={(event) => setOriginLon(event.target.value)}
            inputMode="decimal"
            required
          />
        </fieldset>

        <label className="optimizer__check">
          <input
            type="checkbox"
            data-testid="optimizer-return"
            checked={returnToOrigin}
            onChange={(event) => setReturnToOrigin(event.target.checked)}
          />
          Volver al origen
        </label>

        {returnToOrigin ? null : (
          <fieldset className="optimizer__coords">
            <legend>Retorno</legend>
            <label htmlFor="optimizer-dest-lat">Latitud</label>
            <input
              id="optimizer-dest-lat"
              data-testid="optimizer-dest-lat"
              value={destLat}
              onChange={(event) => setDestLat(event.target.value)}
            />
            <label htmlFor="optimizer-dest-lon">Longitud</label>
            <input
              id="optimizer-dest-lon"
              data-testid="optimizer-dest-lon"
              value={destLon}
              onChange={(event) => setDestLon(event.target.value)}
            />
          </fieldset>
        )}

        <label htmlFor="optimizer-service">Minutos de atención por parada</label>
        <input
          id="optimizer-service"
          data-testid="optimizer-service"
          value={serviceMinutes}
          onChange={(event) => setServiceMinutes(event.target.value)}
          inputMode="numeric"
        />

        <label htmlFor="optimizer-workday">Jornada máxima (minutos, opcional)</label>
        <input
          id="optimizer-workday"
          data-testid="optimizer-workday"
          value={workdayMinutes}
          onChange={(event) => setWorkdayMinutes(event.target.value)}
          inputMode="numeric"
          placeholder="Sin límite"
        />

        {objective === "cost" ? (
          <>
            <label htmlFor="optimizer-cost-km">Coste €/km</label>
            <input
              id="optimizer-cost-km"
              data-testid="optimizer-cost-km"
              value={costPerKm}
              onChange={(event) => setCostPerKm(event.target.value)}
              inputMode="decimal"
            />
            <label htmlFor="optimizer-cost-hour">Coste €/hora</label>
            <input
              id="optimizer-cost-hour"
              data-testid="optimizer-cost-hour"
              value={costPerHour}
              onChange={(event) => setCostPerHour(event.target.value)}
              inputMode="decimal"
            />
          </>
        ) : null}

        <button
          type="submit"
          data-testid="optimizer-submit"
          disabled={busy || !canEdit || !routeId}
        >
          {busy ? "Optimizando…" : "Lanzar optimización"}
        </button>
        {canEdit ? null : (
          <p className="form-error">Solo planificador o admin puede optimizar.</p>
        )}
      </form>

      {job ? (
        <div className="card" data-testid="optimizer-job">
          <h2>Progreso</h2>
          <p data-testid="optimizer-job-status">
            {jobLabel}
            {job.error_code ? ` (${job.error_code})` : ""}
          </p>
          <progress
            data-testid="optimizer-progress"
            max={100}
            value={job.progress}
            aria-label="Progreso de la optimización"
          >
            {job.progress}%
          </progress>
        </div>
      ) : null}

      {route ? (
        <div className="card" data-testid="optimizer-result">
          <h2>Resultado</h2>
          <p data-testid="optimizer-solver-status">
            Solver: {SOLVER_LABELS[route.solver_status ?? ""] ?? route.solver_status ?? "sin revisión"}
          </p>
          {route.solver_status === "infeasible" || route.diagnostics.length > 0 ? (
            <RouteDiagnostics
              diagnostics={route.diagnostics}
              solverStatus={route.solver_status}
            />
          ) : null}
          {route.stops.length > 0 ? (
            <ol data-testid="optimizer-stops">
              {route.stops.map((stop) => (
                <li key={stop.id}>
                  Parada {stop.sequence}: {stop.patient_id.slice(0, 8)}
                </li>
              ))}
            </ol>
          ) : (
            <p>Aún no hay paradas en la revisión actual.</p>
          )}
          {selectedRoute ? (
            <p>
              Estado de ruta: {ROUTE_STATUS[route.status] ?? route.status} · versión{" "}
              {route.version}
            </p>
          ) : null}
        </div>
      ) : null}

      {comparison ? (
        <RouteComparison comparison={comparison} patients={patients} />
      ) : comparisonError ? (
        <p className="form-error" data-testid="comparison-error">
          {comparisonError}
        </p>
      ) : null}

      {route && organizationId ? (
        <RouteExport organizationId={organizationId} route={route} canEdit={canEdit} />
      ) : null}
    </section>
  );
}
