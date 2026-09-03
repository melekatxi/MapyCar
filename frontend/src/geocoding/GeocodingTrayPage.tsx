import { useEffect, useState } from "react";
import {
  MapContainer,
  Marker,
  Popup,
  TileLayer,
  useMapEvents,
} from "react-leaflet";
import "leaflet/dist/leaflet.css";
import { useAuth } from "../auth/AuthContext";
import { listPatients } from "../api/patients";
import {
  confirmGeocodeSelection,
  getAddressCandidates,
} from "../api/geocoding";
import type { AddressCandidates, PatientSummary } from "../api/types";
import { ApiError } from "../api/client";

const NEEDS_REVIEW = new Set(["ambiguous", "not_found"]);
const DEFAULT_CENTER: [number, number] = [43.24, -2.92]; // Bizkaia, ADR-02

function ManualMarkerPicker({
  onPick,
}: {
  onPick: (lat: number, lon: number) => void;
}) {
  useMapEvents({
    click(event) {
      onPick(event.latlng.lat, event.latlng.lng);
    },
  });
  return null;
}

// Bandeja de geocodificación (1.FE.3): candidatos, confianza, mapa de confirmación,
// edición textual y colocación manual del marcador (clic en el mapa). Nunca muestra el
// nombre real del paciente, solo la referencia operativa (ADR-09).
export function GeocodingTrayPage() {
  const { organizationId } = useAuth();
  const [patients, setPatients] = useState<PatientSummary[]>([]);
  const [selected, setSelected] = useState<PatientSummary | null>(null);
  const [candidates, setCandidates] = useState<AddressCandidates | null>(null);
  const [reason, setReason] = useState("");
  const [manualPoint, setManualPoint] = useState<{
    lat: number;
    lon: number;
  } | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!organizationId) return;
    listPatients(organizationId).then((response) =>
      setPatients(
        response.patients.filter((p) => NEEDS_REVIEW.has(p.geocode_status)),
      ),
    );
  }, [organizationId]);

  async function openPatient(patient: PatientSummary) {
    if (!organizationId) return;
    setSelected(patient);
    setMessage(null);
    setManualPoint(null);
    const result = await getAddressCandidates(
      patient.address_id,
      organizationId,
    );
    setCandidates(result);
  }

  async function confirmCandidate(index: number) {
    if (!organizationId || !selected || !reason.trim()) {
      setMessage("Indica un motivo antes de confirmar.");
      return;
    }
    try {
      await confirmGeocodeSelection(selected.address_id, organizationId, {
        candidate_index: index,
        reason,
      });
      setMessage("Dirección confirmada.");
      setSelected(null);
      setCandidates(null);
    } catch (err) {
      setMessage(
        err instanceof ApiError
          ? err.body.detail
          : "No se pudo confirmar el candidato",
      );
    }
  }

  async function confirmManual() {
    if (!organizationId || !selected || !reason.trim() || !manualPoint) {
      setMessage("Coloca un marcador en el mapa e indica un motivo.");
      return;
    }
    try {
      await confirmGeocodeSelection(selected.address_id, organizationId, {
        lat: manualPoint.lat,
        lon: manualPoint.lon,
        reason,
      });
      setMessage("Marcador manual confirmado.");
      setSelected(null);
      setCandidates(null);
      setManualPoint(null);
    } catch (err) {
      setMessage(
        err instanceof ApiError
          ? err.body.detail
          : "No se pudo confirmar el marcador manual",
      );
    }
  }

  const mapCenter: [number, number] = candidates?.candidates.length
    ? [candidates.candidates[0].lat, candidates.candidates[0].lon]
    : DEFAULT_CENTER;

  return (
    <section className="page geocoding-tray">
      <h1>Bandeja de geocodificación</h1>
      <p>{patients.length} direcciones pendientes de revisión.</p>
      <div className="geocoding-tray__layout">
        <ul className="patient-list">
          {patients.map((patient) => (
            <li key={patient.id}>
              <button type="button" onClick={() => openPatient(patient)}>
                {patient.external_ref} · {patient.municipality} ·{" "}
                <em>{patient.geocode_status}</em>
              </button>
            </li>
          ))}
        </ul>

        {selected && candidates && (
          <div className="card geocoding-review">
            <h2>Candidatos para {selected.external_ref}</h2>

            <div className="map-container">
              <MapContainer center={mapCenter} zoom={16} scrollWheelZoom>
                <TileLayer
                  attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
                  url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
                />
                {candidates.candidates.map((candidate, index) => (
                  <Marker
                    key={`${candidate.lat}-${candidate.lon}`}
                    position={[candidate.lat, candidate.lon]}
                  >
                    <Popup>
                      Confianza {candidate.score.toFixed(2)}
                      <br />
                      <button
                        type="button"
                        onClick={() => confirmCandidate(index)}
                      >
                        Elegir este candidato
                      </button>
                    </Popup>
                  </Marker>
                ))}
                {manualPoint && (
                  <Marker position={[manualPoint.lat, manualPoint.lon]}>
                    <Popup>Marcador manual</Popup>
                  </Marker>
                )}
                <ManualMarkerPicker
                  onPick={(lat, lon) => setManualPoint({ lat, lon })}
                />
              </MapContainer>
            </div>
            <p className="hint">
              Haz clic en el mapa para colocar un marcador manual, o abre el
              globo de un candidato para elegirlo directamente.
            </p>

            <label htmlFor="reason">Motivo (obligatorio)</label>
            <input
              id="reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              required
            />
            {manualPoint && (
              <button type="button" onClick={confirmManual}>
                Confirmar marcador manual ({manualPoint.lat.toFixed(5)},{" "}
                {manualPoint.lon.toFixed(5)})
              </button>
            )}

            {message && <p className="banner">{message}</p>}
          </div>
        )}
      </div>
    </section>
  );
}
