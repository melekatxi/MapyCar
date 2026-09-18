import type { RouteComparison as RouteComparisonData } from "../api/types";
import {
  formatCost,
  formatDeviationPct,
  formatDistanceM,
  formatSeconds,
} from "../routing/comparison";

interface PlanExecutionComparisonProps {
  comparison: RouteComparisonData;
}

export function PlanExecutionComparison({ comparison }: PlanExecutionComparisonProps) {
  const planned = comparison.optimized;
  const actual = comparison.actual ?? null;
  const deviation = comparison.deviation ?? null;
  const counts = comparison.execution_counts ?? null;
  const distanceReported = actual != null && actual.distance_m > 0;

  return (
    <div className="card" data-testid="plan-execution">
      <h2>Planificado vs. ejecutado</h2>
      {counts ? (
        <p className="history-counts" data-testid="execution-counts">
          {counts.planned} planificadas · {counts.completed} completadas · {counts.failed}{" "}
          fallidas · {counts.skipped} omitidas · {counts.pending} pendientes
        </p>
      ) : null}

      {actual == null ? (
        <p className="banner" data-testid="execution-empty">
          Aún no hay ejecución reportada para esta ruta.
        </p>
      ) : null}

      <table className="data-table" data-testid="plan-execution-metrics">
        <thead>
          <tr>
            <th>Métrica</th>
            <th>Planificado</th>
            <th>Ejecutado</th>
            <th>Desviación</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <th scope="row">Distancia</th>
            <td>{formatDistanceM(planned.distance_m)}</td>
            <td data-testid="execution-distance">
              {distanceReported && actual ? formatDistanceM(actual.distance_m) : "No reportada"}
            </td>
            <td data-testid="execution-distance-delta">
              {distanceReported && deviation ? formatDistanceM(deviation.distance_m) : "—"}
            </td>
          </tr>
          <tr>
            <th scope="row">Tiempo de viaje</th>
            <td>{formatSeconds(planned.travel_seconds)}</td>
            <td data-testid="execution-travel">
              {actual ? formatSeconds(actual.travel_seconds) : "—"}
            </td>
            <td data-testid="execution-travel-delta">
              {deviation
                ? `${formatSeconds(deviation.travel_seconds)} (${formatDeviationPct(deviation.travel_seconds_pct)})`
                : "—"}
            </td>
          </tr>
          <tr>
            <th scope="row">Tiempo de servicio</th>
            <td>{formatSeconds(planned.service_seconds)}</td>
            <td>{actual ? formatSeconds(actual.service_seconds) : "—"}</td>
            <td>
              {actual
                ? formatSeconds(actual.service_seconds - planned.service_seconds)
                : "—"}
            </td>
          </tr>
          <tr>
            <th scope="row">Coste estimado</th>
            <td>{formatCost(planned.estimated_cost)}</td>
            <td>{actual ? formatCost(actual.estimated_cost) : "—"}</td>
            <td data-testid="execution-cost-delta">
              {deviation ? formatCost(deviation.estimated_cost) : "—"}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}
