import { CircleMarker, MapContainer, Popup, TileLayer } from "react-leaflet";
import type { PatientSummary, RouteComparison as RouteComparisonData } from "../api/types";
import {
  formatCost,
  formatDistanceM,
  formatPct,
  formatSeconds,
} from "./comparison";

const DEFAULT_CENTER: [number, number] = [43.24, -2.92];
const ORIGINAL_COLOR = "#ef6c00";
const OPTIMIZED_COLOR = "#1565c0";

interface RouteComparisonProps {
  comparison: RouteComparisonData;
  patients: PatientSummary[];
}

function coordsFor(
  patientId: string,
  patients: PatientSummary[],
): [number, number] | null {
  const patient = patients.find((item) => item.id === patientId);
  if (patient?.latitude == null || patient.longitude == null) return null;
  return [patient.latitude, patient.longitude];
}

export function RouteComparison({ comparison, patients }: RouteComparisonProps) {
  const optimized = comparison.optimized_stops;
  const original = comparison.original_stops;
  const markers = [
    ...original.flatMap((stop) => {
      const center = coordsFor(stop.patient_id, patients);
      if (!center) return [];
      return [
        {
          key: `original-${stop.sequence}`,
          center,
          sequence: stop.sequence,
          series: "original" as const,
          color: ORIGINAL_COLOR,
          patientId: stop.patient_id,
        },
      ];
    }),
    ...optimized.flatMap((stop) => {
      const center = coordsFor(stop.patient_id, patients);
      if (!center) return [];
      return [
        {
          key: `optimized-${stop.sequence}`,
          center,
          sequence: stop.sequence,
          series: "optimized" as const,
          color: OPTIMIZED_COLOR,
          patientId: stop.patient_id,
        },
      ];
    }),
  ];
  const first = markers[0]?.center ?? DEFAULT_CENTER;
  const { original: base, optimized: best, savings } = comparison;

  return (
    <div className="card" data-testid="route-comparison">
      <h2>Comparación original vs optimizada</h2>
      <table className="data-table" data-testid="comparison-metrics">
        <thead>
          <tr>
            <th>Métrica</th>
            <th>Original</th>
            <th>Optimizada</th>
            <th>Ahorro</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <th scope="row">Distancia</th>
            <td>{formatDistanceM(base.distance_m)}</td>
            <td>{formatDistanceM(best.distance_m)}</td>
            <td data-testid="comparison-savings-distance">
              {formatDistanceM(savings.distance_m)}
            </td>
          </tr>
          <tr>
            <th scope="row">Tiempo de viaje</th>
            <td>{formatSeconds(base.travel_seconds)}</td>
            <td>{formatSeconds(best.travel_seconds)}</td>
            <td data-testid="comparison-savings-travel">
              {formatSeconds(savings.travel_seconds)} ({formatPct(savings.travel_seconds_pct)})
            </td>
          </tr>
          <tr>
            <th scope="row">Coste estimado</th>
            <td>{formatCost(base.estimated_cost)}</td>
            <td>{formatCost(best.estimated_cost)}</td>
            <td data-testid="comparison-savings-cost">{formatCost(savings.estimated_cost)}</td>
          </tr>
        </tbody>
      </table>

      <div className="map-container optimizer__map">
        <MapContainer center={first} zoom={12} scrollWheelZoom>
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
            url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          {markers.map((marker) => (
            <CircleMarker
              key={marker.key}
              center={marker.center}
              pathOptions={{ color: marker.color, fillColor: marker.color, fillOpacity: 0.85 }}
              radius={marker.series === "optimized" ? 10 : 7}
            >
              <Popup>
                {marker.series === "optimized" ? "Optimizada" : "Original"} #{marker.sequence}
              </Popup>
              <span
                data-testid={`comparison-marker-${marker.series}-${marker.sequence}`}
                data-patient={marker.patientId}
              >
                {marker.sequence}
              </span>
            </CircleMarker>
          ))}
        </MapContainer>
        <ul className="map-legend" aria-label="Órdenes de ruta">
          <li>
            <span className="map-legend__swatch" style={{ background: ORIGINAL_COLOR }} />
            Orden original
          </li>
          <li>
            <span className="map-legend__swatch" style={{ background: OPTIMIZED_COLOR }} />
            Orden optimizado (numerado)
          </li>
        </ul>
      </div>
    </div>
  );
}
