import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { CircleMarker, MapContainer, Popup, TileLayer } from "react-leaflet";
import { useAuth } from "../auth/AuthContext";
import { ApiError } from "../api/client";
import { listHistoryRoutes } from "../api/history";
import { getRoute, reportStopExecutionResilient } from "../api/routing";
import { listZones } from "../api/zoning";
import type { HistoryRoute, RouteDetail, RouteStop, StopExecutionStatus } from "../api/types";
import {
  enqueueFieldReport,
  loadFieldOutbox,
  removeFieldReport,
  type FieldOutboxItem,
} from "./outbox";

const DEFAULT_CENTER: [number, number] = [43.24, -2.92];
const STOP_COLOR: Record<string, string> = {
  pending: "#1565c0",
  completed: "#2e7d32",
  failed: "#c62828",
  skipped: "#757575",
};
const STATUS_LABEL: Record<string, string> = {
  pending: "Pendiente",
  completed: "Completada",
  failed: "No completada",
  skipped: "Omitida",
};

function todayInMadrid(): string {
  return new Date().toLocaleDateString("en-CA", { timeZone: "Europe/Madrid" });
}

function errorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.body.detail;
  if (err instanceof Error && err.message) return err.message;
  return fallback;
}

function isNetworkError(err: unknown): boolean {
  return !(err instanceof ApiError);
}

function stopLabel(stop: RouteStop): string {
  return stop.external_ref?.trim() || `Parada ${stop.sequence}`;
}

function windowLabel(stop: RouteStop): string | null {
  if (!stop.window_start && !stop.window_end) return null;
  return `${stop.window_start ?? "—"} – ${stop.window_end ?? "—"}`;
}

export function FieldPage() {
  const { organizationId } = useAuth();
  const [serviceDate, setServiceDate] = useState(todayInMadrid);
  const [routes, setRoutes] = useState<HistoryRoute[]>([]);
  const [zones, setZones] = useState<Record<string, string>>({});
  const [routeId, setRouteId] = useState("");
  const [detail, setDetail] = useState<RouteDetail | null>(null);
  const [outbox, setOutbox] = useState<FieldOutboxItem[]>(() => loadFieldOutbox());
  const [error, setError] = useState<string | null>(null);
  const [busyStop, setBusyStop] = useState<string | null>(null);
  const [failingStop, setFailingStop] = useState<string | null>(null);
  const [failReason, setFailReason] = useState("");

  const zoneName = useCallback(
    (zoneId: string) => zones[zoneId] ?? zoneId.slice(0, 8),
    [zones],
  );

  const loadCatalog = useCallback(async () => {
    if (!organizationId) return;
    const [history, zonePage] = await Promise.all([
      listHistoryRoutes(organizationId, { from: serviceDate, to: serviceDate }),
      listZones(organizationId),
    ]);
    const unique = new Map<string, HistoryRoute>();
    for (const item of history.items) {
      if (!unique.has(item.route_id)) unique.set(item.route_id, item);
    }
    const next = [...unique.values()];
    setRoutes(next);
    setZones(Object.fromEntries(zonePage.zones.map((zone) => [zone.id, zone.name])));
    const ids = new Set(next.map((item) => item.route_id));
    setRouteId((current) => (current && ids.has(current) ? current : next[0]?.route_id || ""));
  }, [organizationId, serviceDate]);

  const loadDetail = useCallback(
    async (id: string) => {
      if (!organizationId || !id) {
        setDetail(null);
        return;
      }
      const route = await getRoute(id, organizationId);
      setDetail(route);
    },
    [organizationId],
  );

  useEffect(() => {
    loadCatalog().catch((err: unknown) => {
      setError(errorMessage(err, "No se pudieron cargar las rutas de campo"));
    });
  }, [loadCatalog]);

  useEffect(() => {
    if (!routeId) {
      setDetail(null);
      return;
    }
    loadDetail(routeId).catch((err: unknown) => {
      setError(errorMessage(err, "No se pudo cargar la ruta"));
    });
  }, [routeId, loadDetail]);

  const flushOutbox = useCallback(async () => {
    if (!organizationId) return;
    const pending = loadFieldOutbox();
    for (const item of pending) {
      try {
        const reported = await reportStopExecutionResilient(item);
        setOutbox(removeFieldReport(item.stopId));
        setDetail((current) => {
          if (!current || current.id !== item.routeId) return current;
          return {
            ...current,
            status: reported.route_status || current.status,
            stops: current.stops.map((stop) =>
              stop.id === item.stopId
                ? {
                    ...stop,
                    status: reported.status,
                    version: reported.version,
                    completed_at: reported.completed_at,
                    failure_reason: reported.failure_reason,
                  }
                : stop,
            ),
          };
        });
      } catch (err) {
        if (isNetworkError(err)) return;
        setError(errorMessage(err, "No se pudo reenviar el reporte"));
        return;
      }
    }
  }, [organizationId]);

  useEffect(() => {
    const onOnline = () => {
      void flushOutbox();
    };
    window.addEventListener("online", onOnline);
    return () => window.removeEventListener("online", onOnline);
  }, [flushOutbox]);

  const report = async (
    stop: RouteStop,
    status: StopExecutionStatus,
    failure_reason?: string,
  ) => {
    if (!organizationId || !detail || stop.version == null) return;
    setBusyStop(stop.id);
    setError(null);
    const payload = {
      routeId: detail.id,
      stopId: stop.id,
      organizationId,
      version: stop.version,
      status,
      failure_reason,
    };
    try {
      const reported = await reportStopExecutionResilient(payload);
      setOutbox(removeFieldReport(stop.id));
      setDetail({
        ...detail,
        status: reported.route_status || detail.status,
        stops: detail.stops.map((item) =>
          item.id === stop.id
            ? {
                ...item,
                status: reported.status,
                version: reported.version,
                completed_at: reported.completed_at,
                failure_reason: reported.failure_reason,
              }
            : item,
        ),
      });
      setFailingStop(null);
      setFailReason("");
    } catch (err) {
      if (isNetworkError(err)) {
        setOutbox(enqueueFieldReport(payload));
        setError("Sin conexión. El reporte se enviará al reconectar.");
        return;
      }
      setError(errorMessage(err, "No se pudo reportar la parada"));
    } finally {
      setBusyStop(null);
    }
  };

  const handleDate = (event: FormEvent) => {
    event.preventDefault();
    setRouteId("");
    void loadCatalog();
  };

  const markers = useMemo(() => {
    return (detail?.stops ?? []).flatMap((stop) => {
      if (stop.lat == null || stop.lon == null) return [];
      return [{ stop, center: [stop.lat, stop.lon] as [number, number] }];
    });
  }, [detail]);
  const mapCenter = markers[0]?.center ?? DEFAULT_CENTER;
  const pendingOutbox = outbox.filter((item) => item.routeId === routeId);

  return (
    <section className="page field-page">
      <h1>Ruta de campo</h1>
      <p>
        Marca visitas completadas o no completadas. Si se corta la red, el reporte se
        reenvía al reconectar. No se guardan teselas del mapa.
      </p>

      {error ? (
        <p className="form-error" role="alert">
          {error}
        </p>
      ) : null}

      {pendingOutbox.length > 0 ? (
        <div className="banner" data-testid="field-outbox">
          <p>Hay {pendingOutbox.length} reporte(s) pendientes de enviar.</p>
          <button type="button" data-testid="field-reconnect" onClick={() => void flushOutbox()}>
            Reconectar
          </button>
        </div>
      ) : null}

      <form className="form field-page__filters" onSubmit={handleDate}>
        <label htmlFor="field-date">Fecha de visita</label>
        <input
          id="field-date"
          data-testid="field-date"
          type="date"
          value={serviceDate}
          onChange={(event) => setServiceDate(event.target.value)}
        />
        <label htmlFor="field-route">Ruta</label>
        <select
          id="field-route"
          data-testid="field-route"
          value={routeId}
          onChange={(event) => setRouteId(event.target.value)}
        >
          {routes.length === 0 ? <option value="">Sin rutas publicadas</option> : null}
          {routes.map((item) => (
            <option key={item.route_id} value={item.route_id}>
              {item.service_date} · {zoneName(item.zone_id)}
            </option>
          ))}
        </select>
      </form>

      {detail ? (
        <>
          <p data-testid="field-route-status">
            Estado de la ruta: {detail.status}
          </p>
          <ol className="field-stops">
            {detail.stops.map((stop) => {
              const queued = pendingOutbox.some((item) => item.stopId === stop.id);
              return (
                <li
                  key={stop.id}
                  className="field-stop"
                  data-testid={`field-stop-${stop.id}`}
                  data-status={stop.status ?? "pending"}
                >
                  <div>
                    <strong>
                      #{stop.sequence} {stopLabel(stop)}
                    </strong>
                    <p>{STATUS_LABEL[stop.status ?? "pending"]}</p>
                    {windowLabel(stop) ? <p>Ventana {windowLabel(stop)}</p> : null}
                    {queued ? <p data-testid={`field-queued-${stop.id}`}>Pendiente de enviar</p> : null}
                  </div>
                  {stop.status === "pending" || queued ? (
                    <div className="field-stop__actions">
                      <button
                        type="button"
                        data-testid={`field-complete-${stop.id}`}
                        disabled={busyStop === stop.id}
                        onClick={() => void report(stop, "completed")}
                      >
                        Completada
                      </button>
                      <button
                        type="button"
                        className="button-secondary"
                        data-testid={`field-skip-${stop.id}`}
                        disabled={busyStop === stop.id}
                        onClick={() => void report(stop, "skipped")}
                      >
                        Omitir
                      </button>
                      <button
                        type="button"
                        className="button-secondary"
                        data-testid={`field-fail-${stop.id}`}
                        disabled={busyStop === stop.id}
                        onClick={() => {
                          setFailingStop(stop.id);
                          setFailReason("");
                        }}
                      >
                        No completada
                      </button>
                    </div>
                  ) : null}
                  {failingStop === stop.id ? (
                    <form
                      className="field-stop__fail"
                      onSubmit={(event) => {
                        event.preventDefault();
                        void report(stop, "failed", failReason);
                      }}
                    >
                      <label htmlFor={`field-reason-${stop.id}`}>Motivo</label>
                      <input
                        id={`field-reason-${stop.id}`}
                        data-testid={`field-reason-${stop.id}`}
                        value={failReason}
                        onChange={(event) => setFailReason(event.target.value)}
                        required
                      />
                      <button type="submit" data-testid={`field-fail-submit-${stop.id}`}>
                        Confirmar
                      </button>
                    </form>
                  ) : null}
                </li>
              );
            })}
          </ol>

          {markers.length > 0 ? (
            <div className="map-container optimizer__map">
              <MapContainer center={mapCenter} zoom={12} scrollWheelZoom>
                <TileLayer
                  attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
                  url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
                />
                {markers.map(({ stop, center }) => (
                  <CircleMarker
                    key={stop.id}
                    center={center}
                    pathOptions={{
                      color: STOP_COLOR[stop.status ?? "pending"],
                      fillColor: STOP_COLOR[stop.status ?? "pending"],
                      fillOpacity: 0.85,
                    }}
                    radius={10}
                  >
                    <Popup>
                      #{stop.sequence} {stopLabel(stop)}
                    </Popup>
                    <span data-testid={`field-marker-${stop.sequence}`}>{stop.sequence}</span>
                  </CircleMarker>
                ))}
              </MapContainer>
            </div>
          ) : null}
        </>
      ) : null}
    </section>
  );
}
