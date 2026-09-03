import { useEffect, useState } from "react";
import { MapContainer, TileLayer, CircleMarker, Popup } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import { useAuth } from "../auth/AuthContext";
import { listPatients } from "../api/patients";
import type { GeocodeStatus, PatientSummary, VisitStatus } from "../api/types";
import { PatientDetailPanel } from "./PatientDetailPanel";

// Centro aproximado de Bizkaia; ADR-02 (Leaflet + OSM, sin Google Maps/Mapbox).
const DEFAULT_CENTER: [number, number] = [43.24, -2.92];
const DEFAULT_ZOOM = 10;

// RF-07 (1.FE.5): relleno = estado de visita. Hasta Fase 2 DailyRoute todos
// llegan como "pending"; la leyenda enseña los tres colores igualmente.
const VISIT_COLORS: Record<VisitStatus, string> = {
  pending: "#ef6c00",
  planned: "#5e35b1",
  completed: "#2e7d32",
};

const VISIT_LABELS: Record<VisitStatus, string> = {
  pending: "Pendiente",
  planned: "Planificada",
  completed: "Completada",
};

// Leyenda operativa de geocodificación (borde del marcador). No borrar: es
// distinta de RF-07 y sigue siendo la señal de calidad de la dirección.
const GEOCODE_COLORS: Record<GeocodeStatus, string> = {
  pending: "#9aa0a6",
  matched: "#2e7d32",
  ambiguous: "#f9a825",
  not_found: "#c62828",
  manual: "#1565c0",
};

const GEOCODE_LABELS: Record<GeocodeStatus, string> = {
  pending: "Pendiente de geocodificar",
  matched: "Geocodificada",
  ambiguous: "Ambigua",
  not_found: "No encontrada",
  manual: "Confirmada manualmente",
};

export function OperationalMapPage() {
  const { organizationId } = useAuth();
  const [patients, setPatients] = useState<PatientSummary[]>([]);
  const [selected, setSelected] = useState<PatientSummary | null>(null);

  useEffect(() => {
    if (!organizationId) return;
    listPatients(organizationId).then((response) =>
      setPatients(response.patients),
    );
  }, [organizationId]);

  const located = patients.filter(
    (p) => p.latitude !== null && p.longitude !== null,
  );

  return (
    <section className="page map-page">
      <h1>Mapa operativo</h1>
      <div className="map-page__layout">
        <div className="map-container">
          <MapContainer
            center={DEFAULT_CENTER}
            zoom={DEFAULT_ZOOM}
            scrollWheelZoom
          >
            <TileLayer
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
              url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
            />
            {located.map((patient) => (
              <CircleMarker
                key={patient.id}
                center={[
                  patient.latitude as number,
                  patient.longitude as number,
                ]}
                radius={8}
                pathOptions={{
                  color: GEOCODE_COLORS[patient.geocode_status],
                  fillColor: VISIT_COLORS[patient.visit_status],
                  fillOpacity: 0.85,
                  weight: 3,
                }}
                eventHandlers={{ click: () => setSelected(patient) }}
              >
                <Popup>{patient.external_ref}</Popup>
              </CircleMarker>
            ))}
          </MapContainer>
          <div className="map-legends">
            <div>
              <p className="map-legend__title">Estado de visita</p>
              <ul className="map-legend" aria-label="Estado de visita">
                {Object.entries(VISIT_LABELS).map(([status, label]) => (
                  <li key={status}>
                    <span
                      className="map-legend__swatch"
                      style={{
                        background: VISIT_COLORS[status as VisitStatus],
                      }}
                    />
                    {label}
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <p className="map-legend__title">Geocodificación</p>
              <ul className="map-legend" aria-label="Geocodificación">
                {Object.entries(GEOCODE_LABELS).map(([status, label]) => (
                  <li key={status}>
                    <span
                      className="map-legend__swatch"
                      style={{
                        background: GEOCODE_COLORS[status as GeocodeStatus],
                      }}
                    />
                    {label}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>
        <PatientDetailPanel
          patient={selected}
          statusLabel={selected ? GEOCODE_LABELS[selected.geocode_status] : ""}
          visitLabel={selected ? VISIT_LABELS[selected.visit_status] : ""}
        />
      </div>
    </section>
  );
}
