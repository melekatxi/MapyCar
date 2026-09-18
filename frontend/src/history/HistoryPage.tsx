import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { useAuth } from "../auth/AuthContext";
import { ApiError } from "../api/client";
import { listHistoryRoutes } from "../api/history";
import { getRouteComparison } from "../api/routing";
import { listZones } from "../api/zoning";
import type {
  HistoryRoute,
  RouteComparison as RouteComparisonData,
  ZoneSummary,
} from "../api/types";
import { HistorySnapshot } from "./HistorySnapshot";
import { PlanExecutionComparison } from "./PlanExecutionComparison";

function errorMessage(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.body.detail : fallback;
}

function shortId(value: string): string {
  return value.replaceAll("-", "").slice(0, 8);
}

export function HistoryPage() {
  const { organizationId, user } = useAuth();
  const [zones, setZones] = useState<ZoneSummary[]>([]);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [zoneId, setZoneId] = useState("");
  const [assigneeId, setAssigneeId] = useState("");
  const [patientRef, setPatientRef] = useState("");
  const [items, setItems] = useState<HistoryRoute[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [selected, setSelected] = useState<HistoryRoute | null>(null);
  const [comparison, setComparison] = useState<RouteComparisonData | null>(null);
  const [comparisonError, setComparisonError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const role = user?.memberships.find((item) => item.organization_id === organizationId)?.role;
  const canFilterAssignee = role !== "field";

  const zoneName = useCallback(
    (id: string) => zones.find((zone) => zone.id === id)?.name ?? shortId(id),
    [zones],
  );

  const assigneeLabel = useCallback(
    (id: string) => {
      if (user && id === user.id) return user.display_name;
      return shortId(id);
    },
    [user],
  );

  const assigneeOptions = useMemo(() => {
    const ids = new Set<string>();
    if (user) ids.add(user.id);
    for (const item of items) ids.add(item.assignee_id);
    if (assigneeId) ids.add(assigneeId);
    return [...ids];
  }, [user, items, assigneeId]);

  const loadZones = useCallback(async () => {
    if (!organizationId) return;
    const response = await listZones(organizationId);
    setZones(response.zones);
  }, [organizationId]);

  const search = useCallback(
    async (append: boolean, cursor?: string) => {
      if (!organizationId) return;
      setBusy(true);
      setError(null);
      try {
        const page = await listHistoryRoutes(organizationId, {
          from: from || undefined,
          to: to || undefined,
          zone: zoneId || undefined,
          assignee: canFilterAssignee && assigneeId ? assigneeId : undefined,
          patient_ref: patientRef || undefined,
          cursor,
        });
        setItems((current) => (append ? [...current, ...page.items] : page.items));
        setNextCursor(page.next_cursor);
        if (!append) {
          setSelected(null);
          setComparison(null);
          setComparisonError(null);
        }
      } catch (err) {
        setError(errorMessage(err, "No se pudo cargar el histórico"));
      } finally {
        setBusy(false);
      }
    },
    [organizationId, from, to, zoneId, assigneeId, patientRef, canFilterAssignee],
  );

  useEffect(() => {
    loadZones().catch((err: unknown) => {
      setError(errorMessage(err, "No se pudieron cargar las zonas"));
    });
  }, [loadZones]);

  useEffect(() => {
    if (!organizationId) return;
    let cancelled = false;
    setBusy(true);
    listHistoryRoutes(organizationId, {})
      .then((page) => {
        if (cancelled) return;
        setItems(page.items);
        setNextCursor(page.next_cursor);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(errorMessage(err, "No se pudo cargar el histórico"));
      })
      .finally(() => {
        if (!cancelled) setBusy(false);
      });
    return () => {
      cancelled = true;
    };
  }, [organizationId]);

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    void search(false);
  };

  const selectItem = async (item: HistoryRoute) => {
    setSelected(item);
    setComparison(null);
    setComparisonError(null);
    if (!organizationId) return;
    try {
      const data = await getRouteComparison(item.route_id, organizationId);
      setComparison(data);
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        setComparisonError("No tienes permiso para ver la comparativa de ejecución.");
        return;
      }
      setComparisonError(errorMessage(err, "No se pudo cargar la comparativa"));
    }
  };

  return (
    <section className="page history">
      <h1>Histórico de rutas</h1>
      <p>
        Consulta snapshots publicados (no el paciente actual). Filtra por fecha, zona,
        visitador o referencia y compara el plan con la ejecución reportada.
      </p>

      {error ? (
        <p className="form-error" role="alert">
          {error}
        </p>
      ) : null}

      <form className="form history-filters" onSubmit={handleSubmit}>
        <label htmlFor="history-from">Desde</label>
        <input
          id="history-from"
          data-testid="history-from"
          type="date"
          value={from}
          onChange={(event) => setFrom(event.target.value)}
        />
        <label htmlFor="history-to">Hasta</label>
        <input
          id="history-to"
          data-testid="history-to"
          type="date"
          value={to}
          onChange={(event) => setTo(event.target.value)}
        />
        <label htmlFor="history-zone">Zona</label>
        <select
          id="history-zone"
          data-testid="history-zone"
          value={zoneId}
          onChange={(event) => setZoneId(event.target.value)}
        >
          <option value="">Todas</option>
          {zones.map((zone) => (
            <option key={zone.id} value={zone.id}>
              {zone.name}
            </option>
          ))}
        </select>
        {canFilterAssignee ? (
          <>
            <label htmlFor="history-assignee">Visitador</label>
            <select
              id="history-assignee"
              data-testid="history-assignee"
              value={assigneeId}
              onChange={(event) => setAssigneeId(event.target.value)}
            >
              <option value="">Todos</option>
              {assigneeOptions.map((id) => (
                <option key={id} value={id}>
                  {assigneeLabel(id)}
                </option>
              ))}
            </select>
          </>
        ) : null}
        <label htmlFor="history-ref">Referencia de paciente</label>
        <input
          id="history-ref"
          data-testid="history-ref"
          value={patientRef}
          onChange={(event) => setPatientRef(event.target.value)}
          placeholder="PAC-001"
        />
        <div className="actions">
          <button type="submit" data-testid="history-search" disabled={busy}>
            Buscar
          </button>
        </div>
      </form>

      <div className="history-layout">
        <div className="card">
          <h2>Rutas publicadas</h2>
          {items.length === 0 ? (
            <p data-testid="history-empty">No hay rutas publicadas en este filtro.</p>
          ) : (
            <table className="data-table" data-testid="history-results">
              <thead>
                <tr>
                  <th>Fecha</th>
                  <th>Zona</th>
                  <th>Visitador</th>
                  <th>Paradas</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => {
                  const selectedRow = selected?.revision_id === item.revision_id;
                  return (
                    <tr
                      key={item.revision_id}
                      className={selectedRow ? "history-row--selected" : undefined}
                    >
                      <td>{item.service_date}</td>
                      <td>{zoneName(item.zone_id)}</td>
                      <td>{assigneeLabel(item.assignee_id)}</td>
                      <td>{item.stops.length}</td>
                      <td>
                        <button
                          type="button"
                          className="button-secondary"
                          data-testid={`history-open-${item.revision_id}`}
                          aria-pressed={selectedRow}
                          onClick={() => {
                            void selectItem(item);
                          }}
                        >
                          Ver snapshot
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
          {nextCursor ? (
            <div className="actions">
              <button
                type="button"
                className="button-secondary"
                data-testid="history-more"
                disabled={busy}
                onClick={() => {
                  void search(true, nextCursor);
                }}
              >
                Cargar más
              </button>
            </div>
          ) : null}
        </div>

        {selected ? (
          <div className="history-detail">
            <HistorySnapshot
              item={selected}
              zoneName={zoneName(selected.zone_id)}
              assigneeLabel={assigneeLabel(selected.assignee_id)}
            />
            {comparisonError ? (
              <p className="form-error" role="alert" data-testid="comparison-error">
                {comparisonError}
              </p>
            ) : null}
            {comparison ? <PlanExecutionComparison comparison={comparison} /> : null}
          </div>
        ) : null}
      </div>
    </section>
  );
}
