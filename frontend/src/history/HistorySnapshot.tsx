import { CircleMarker, MapContainer, Popup, TileLayer } from "react-leaflet";
import type { HistoryRoute, HistoryStop } from "../api/types";

const DEFAULT_CENTER: [number, number] = [43.24, -2.92];
const STOP_COLOR = "#1565c0";

interface HistorySnapshotProps {
  item: HistoryRoute;
  zoneName: string;
  assigneeLabel: string;
}

function stopLabel(stop: HistoryStop): string {
  return stop.external_ref?.trim() || `Parada ${stop.sequence}`;
}

function formatPublishedAt(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString("es-ES", { timeZone: "Europe/Madrid" });
}

export function HistorySnapshot({ item, zoneName, assigneeLabel }: HistorySnapshotProps) {
  const markers = item.stops.flatMap((stop) => {
    if (stop.lat == null || stop.lon == null) return [];
    return [{ stop, center: [stop.lat, stop.lon] as [number, number] }];
  });
  const first = markers[0]?.center ?? DEFAULT_CENTER;

  return (
    <div className="card" data-testid="history-snapshot">
      <h2>Snapshot publicado</h2>
      <dl className="history-meta">
        <div>
          <dt>Fecha de visita</dt>
          <dd data-testid="snapshot-date">{item.service_date}</dd>
        </div>
        <div>
          <dt>Zona</dt>
          <dd data-testid="snapshot-zone">{zoneName}</dd>
        </div>
        <div>
          <dt>Visitador</dt>
          <dd data-testid="snapshot-assignee">{assigneeLabel}</dd>
        </div>
        <div>
          <dt>Publicado</dt>
          <dd>{formatPublishedAt(item.published_at)}</dd>
        </div>
        <div>
          <dt>Revisión</dt>
          <dd>{item.revision}</dd>
        </div>
      </dl>

      <table className="data-table" data-testid="snapshot-stops">
        <thead>
          <tr>
            <th>#</th>
            <th>Referencia</th>
          </tr>
        </thead>
        <tbody>
          {item.stops.map((stop) => (
            <tr key={`${stop.patient_id}-${stop.sequence}`}>
              <td>{stop.sequence}</td>
              <td data-testid={`snapshot-stop-${stop.sequence}`}>{stopLabel(stop)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {markers.length > 0 ? (
        <div className="map-container optimizer__map">
          <MapContainer center={first} zoom={12} scrollWheelZoom>
            <TileLayer
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
              url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
            />
            {markers.map(({ stop, center }) => (
              <CircleMarker
                key={`snap-${stop.sequence}`}
                center={center}
                pathOptions={{ color: STOP_COLOR, fillColor: STOP_COLOR, fillOpacity: 0.85 }}
                radius={10}
              >
                <Popup>
                  #{stop.sequence} {stopLabel(stop)}
                </Popup>
                <span data-testid={`snapshot-marker-${stop.sequence}`}>{stop.sequence}</span>
              </CircleMarker>
            ))}
          </MapContainer>
        </div>
      ) : null}
    </div>
  );
}
