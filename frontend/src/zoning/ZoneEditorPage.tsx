import { useCallback, useEffect, useMemo, useState, type DragEvent, type FormEvent } from "react";
import { CircleMarker, MapContainer, Popup, TileLayer } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import { useAuth } from "../auth/AuthContext";
import { ApiError } from "../api/client";
import { listPatients } from "../api/patients";
import {
  acceptZoneProposal,
  createZoneProposal,
  listZones,
  pollZoneProposal,
} from "../api/zoning";
import type { PatientSummary, ZoneProposal, ZoneSummary } from "../api/types";
import {
  confirmZoneReassign,
  dropPatientOnZone,
  parseDraggedPatientId,
} from "./reassign";
import { ZoneKindBadge, ZoneKindLegend } from "./ZoneKindBadge";

const DEFAULT_CENTER: [number, number] = [43.24, -2.92];
const DEFAULT_ZOOM = 10;
const ZONE_COLORS = ["#1565c0", "#6a1b9a", "#00838f", "#ef6c00", "#2e7d32", "#ad1457"];
const OUTLIER_COLOR = "#9aa0a6";

function colorForKey(key: string, keys: string[]): string {
  const index = Math.max(0, keys.indexOf(key));
  return ZONE_COLORS[index % ZONE_COLORS.length];
}

function errorMessage(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.body.detail : fallback;
}

function capacityLabel(count: number, maxVisits: number | null | undefined): string {
  return maxVisits == null ? `${count} / sin límite` : `${count} / ${maxVisits}`;
}

export function ZoneEditorPage() {
  const { organizationId } = useAuth();
  const [maxVisits, setMaxVisits] = useState("20");
  const [targetZones, setTargetZones] = useState("");
  const [resetOverrides, setResetOverrides] = useState(false);
  const [patients, setPatients] = useState<PatientSummary[]>([]);
  const [zones, setZones] = useState<ZoneSummary[]>([]);
  const [proposal, setProposal] = useState<ZoneProposal | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [formPatientId, setFormPatientId] = useState("");
  const [formZoneId, setFormZoneId] = useState("");
  const [formReason, setFormReason] = useState("");
  const [pending, setPending] = useState<{ patientId: string; targetZoneId: string } | null>(null);
  const [modalReason, setModalReason] = useState("");
  const [dragOverZoneId, setDragOverZoneId] = useState<string | null>(null);

  const refreshPublished = useCallback(async () => {
    if (!organizationId) return;
    const [zoneResponse, patientResponse] = await Promise.all([
      listZones(organizationId),
      listPatients(organizationId),
    ]);
    setZones(zoneResponse.zones);
    setPatients(patientResponse.patients);
  }, [organizationId]);

  useEffect(() => {
    refreshPublished().catch((err) => {
      setError(errorMessage(err, "No se pudieron cargar las zonas"));
    });
  }, [refreshPublished]);

  const patientsById = useMemo(
    () => new Map(patients.map((patient) => [patient.id, patient])),
    [patients],
  );
  const zoneIds = useMemo(() => zones.map((zone) => zone.id), [zones]);
  const clusterIds = useMemo(
    () => proposal?.clusters.map((cluster) => cluster.cluster_id) ?? [],
    [proposal],
  );

  async function handleGenerate(event: FormEvent) {
    event.preventDefault();
    if (!organizationId) return;
    const parsedMax = Number.parseInt(maxVisits, 10);
    if (!Number.isFinite(parsedMax) || parsedMax < 1) {
      setError("Indica un máximo de visitas por zona mayor que 0.");
      return;
    }
    const parsedTarget = targetZones.trim()
      ? Number.parseInt(targetZones, 10)
      : undefined;
    if (parsedTarget !== undefined && (!Number.isFinite(parsedTarget) || parsedTarget < 1)) {
      setError("El número de zonas debe ser un entero mayor que 0.");
      return;
    }
    setBusy(true);
    setError(null);
    setMessage("Generando propuesta…");
    try {
      const created = await createZoneProposal({
        organization_id: organizationId,
        max_visits: parsedMax,
        target_zones: parsedTarget,
      });
      const ready = await pollZoneProposal(created.id, organizationId);
      setProposal(ready);
      if (ready.status === "failed") {
        setError(ready.error_code ?? "La propuesta ha fallado");
        setMessage(null);
      } else {
        setMessage("Propuesta lista. Revisa los clústeres y acéptala para editar.");
      }
    } catch (err) {
      setError(errorMessage(err, "No se pudo generar la propuesta"));
      setMessage(null);
    } finally {
      setBusy(false);
    }
  }

  async function handleAccept() {
    if (!organizationId || !proposal) return;
    setBusy(true);
    setError(null);
    try {
      await acceptZoneProposal(proposal.id, organizationId, resetOverrides);
      await refreshPublished();
      setMessage("Zonas publicadas. Arrastra un paciente o usa el formulario para reasignar.");
    } catch (err) {
      setError(errorMessage(err, "No se pudo aceptar la propuesta"));
    } finally {
      setBusy(false);
    }
  }

  function openConfirm(patientId: string, targetZoneId: string) {
    const currentZoneId = patientsById.get(patientId)?.zone_id ?? null;
    const intent = dropPatientOnZone(patientId, targetZoneId, currentZoneId);
    if (!intent) return;
    setPending(intent);
    setModalReason("");
    setError(null);
  }

  function handleDragStart(patientId: string, event: DragEvent<HTMLElement>) {
    event.dataTransfer.setData("text/plain", patientId);
    event.dataTransfer.effectAllowed = "move";
  }

  function handleDropOnZone(zoneId: string, event: DragEvent<HTMLElement>) {
    event.preventDefault();
    setDragOverZoneId(null);
    const patientId = parseDraggedPatientId(event.dataTransfer);
    if (patientId) openConfirm(patientId, zoneId);
  }

  async function submitReassign(patientId: string, zoneId: string, reason: string) {
    if (!organizationId) return;
    const zone = zones.find((item) => item.id === zoneId);
    if (!zone) {
      setError("Selecciona una zona de destino.");
      return;
    }
    try {
      await confirmZoneReassign({
        organizationId,
        zoneId,
        patientId,
        reason,
        version: zone.version,
      });
      setPending(null);
      setModalReason("");
      setFormReason("");
      await refreshPublished();
      setMessage("Reasignación guardada.");
      setError(null);
    } catch (err) {
      setError(
        err instanceof Error && !(err instanceof ApiError)
          ? err.message
          : errorMessage(err, "No se pudo reasignar el paciente"),
      );
    }
  }

  async function handleFormReassign(event: FormEvent) {
    event.preventDefault();
    await submitReassign(formPatientId, formZoneId, formReason);
  }

  const proposalLocated = useMemo(() => {
    if (!proposal) return [];
    const clusterByPatient = new Map(
      proposal.assignments.map((item) => [item.patient_id, item.cluster_id]),
    );
    const outlierSet = new Set(proposal.outliers);
    return patients.filter(
      (patient) =>
        patient.latitude !== null &&
        patient.longitude !== null &&
        (clusterByPatient.has(patient.id) || outlierSet.has(patient.id)),
    );
  }, [proposal, patients]);

  const publishedLocated = patients.filter(
    (patient) => patient.latitude !== null && patient.longitude !== null,
  );

  const unassigned = patients.filter((patient) => !patient.zone_id);

  return (
    <section className="page zone-editor">
      <h1>Zonas</h1>
      <p>
        Genera una propuesta de agrupación, acéptala y reasigna pacientes. El
        motivo es obligatorio y se envía con la versión de la zona (If-Match).
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

      <form className="card form" onSubmit={handleGenerate}>
        <h2>Parámetros de propuesta</h2>
        <label htmlFor="max-visits">Máximo de visitas por zona</label>
        <input
          id="max-visits"
          type="number"
          min={1}
          required
          value={maxVisits}
          onChange={(event) => setMaxVisits(event.target.value)}
        />
        <label htmlFor="target-zones">Número de zonas (opcional)</label>
        <input
          id="target-zones"
          type="number"
          min={1}
          value={targetZones}
          onChange={(event) => setTargetZones(event.target.value)}
        />
        <button type="submit" disabled={busy || !organizationId}>
          {busy ? "Generando…" : "Generar propuesta"}
        </button>
      </form>

      {proposal && (
        <section className="card">
          <h2>Propuesta</h2>
          <p>
            Estado: <strong>{proposal.status}</strong>
            {proposal.metrics
              ? ` · ${proposal.metrics.n_clusters} zonas · ${proposal.metrics.n_outliers} sin asignar`
              : null}
          </p>
          <ul className="zone-cards" aria-label="Capacidad de la propuesta">
            {proposal.clusters.map((cluster) => (
              <li key={cluster.cluster_id} className="zone-card">
                <h3>{cluster.cluster_id}</h3>
                <ZoneKindBadge kind={cluster.kind} />
                <p data-testid={`proposal-capacity-${cluster.cluster_id}`}>
                  Capacidad:{" "}
                  {capacityLabel(
                    cluster.member_ids.length,
                    proposal.metrics?.max_visits ?? null,
                  )}
                </p>
              </li>
            ))}
          </ul>
          {proposal.outliers.length > 0 && (
            <p>
              Sin zona: {proposal.outliers.length} paciente
              {proposal.outliers.length === 1 ? "" : "s"}
            </p>
          )}
          <div className="map-container">
            <MapContainer center={DEFAULT_CENTER} zoom={DEFAULT_ZOOM} scrollWheelZoom>
              <TileLayer
                attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
                url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
              />
              {proposalLocated.map((patient) => {
                const clusterId = proposal.assignments.find(
                  (item) => item.patient_id === patient.id,
                )?.cluster_id;
                const color = clusterId
                  ? colorForKey(clusterId, clusterIds)
                  : OUTLIER_COLOR;
                return (
                  <CircleMarker
                    key={patient.id}
                    center={[patient.latitude as number, patient.longitude as number]}
                    radius={8}
                    pathOptions={{ color, fillColor: color, fillOpacity: 0.85, weight: 3 }}
                  >
                    <Popup>{patient.external_ref}</Popup>
                  </CircleMarker>
                );
              })}
            </MapContainer>
            <ZoneKindLegend />
          </div>
          <label className="zone-editor__check">
            <input
              type="checkbox"
              checked={resetOverrides}
              onChange={(event) => setResetOverrides(event.target.checked)}
            />
            Restablecer reasignaciones manuales al aceptar
          </label>
          <button
            type="button"
            onClick={handleAccept}
            disabled={busy || proposal.status !== "succeeded"}
          >
            Aceptar propuesta
          </button>
        </section>
      )}

      {zones.length > 0 && (
        <section className="card">
          <h2>Zonas publicadas</h2>
          <p>
            Arrastra un paciente a otra zona o usa el formulario de reasignación
            si no puedes arrastrar.
          </p>
          <ul className="zone-cards" aria-label="Zonas publicadas">
            {zones.map((zone) => {
              const members = patients.filter((patient) => patient.zone_id === zone.id);
              const full =
                zone.max_visits != null && zone.patient_count >= zone.max_visits;
              return (
                <li
                  key={zone.id}
                  className={`zone-card ${full ? "zone-card--full" : ""} ${
                    dragOverZoneId === zone.id ? "zone-card--over" : ""
                  }`}
                  data-testid={`zone-card-${zone.id}`}
                  onDragOver={(event) => {
                    event.preventDefault();
                    setDragOverZoneId(zone.id);
                  }}
                  onDragLeave={() => setDragOverZoneId(null)}
                  onDrop={(event) => handleDropOnZone(zone.id, event)}
                >
                  <h3>{zone.name}</h3>
                  <ZoneKindBadge kind={zone.kind} />
                  <p
                    data-testid={`capacity-${zone.id}`}
                    aria-label={`Capacidad de ${zone.name}: ${capacityLabel(zone.patient_count, zone.max_visits)}`}
                  >
                    Capacidad: {capacityLabel(zone.patient_count, zone.max_visits)}
                  </p>
                  <ul className="zone-card__patients" aria-label={`Pacientes de ${zone.name}`}>
                    {members.map((patient) => (
                      <li
                        key={patient.id}
                        draggable
                        data-testid={`zone-patient-${patient.id}`}
                        onDragStart={(event) => handleDragStart(patient.id, event)}
                      >
                        <span>{patient.external_ref}</span>
                        <ZoneKindBadge kind={zone.kind} />
                      </li>
                    ))}
                  </ul>
                </li>
              );
            })}
          </ul>
          {unassigned.length > 0 && (
            <div className="zone-card">
              <h3>Sin zona</h3>
              <ul className="zone-card__patients" aria-label="Pacientes sin zona">
                {unassigned.map((patient) => (
                  <li
                    key={patient.id}
                    draggable
                    data-testid={`zone-patient-${patient.id}`}
                    onDragStart={(event) => handleDragStart(patient.id, event)}
                  >
                    {patient.external_ref}
                  </li>
                ))}
              </ul>
            </div>
          )}
          <div className="map-container">
            <MapContainer center={DEFAULT_CENTER} zoom={DEFAULT_ZOOM} scrollWheelZoom>
              <TileLayer
                attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
                url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
              />
              {publishedLocated.map((patient) => {
                const color = patient.zone_id
                  ? colorForKey(patient.zone_id, zoneIds)
                  : OUTLIER_COLOR;
                return (
                  <CircleMarker
                    key={patient.id}
                    center={[patient.latitude as number, patient.longitude as number]}
                    radius={8}
                    pathOptions={{ color, fillColor: color, fillOpacity: 0.85, weight: 3 }}
                    eventHandlers={{
                      click: () => {
                        setFormPatientId(patient.id);
                        if (patient.zone_id) setFormZoneId(patient.zone_id);
                      },
                    }}
                  >
                    <Popup>{patient.external_ref}</Popup>
                  </CircleMarker>
                );
              })}
            </MapContainer>
            <ZoneKindLegend />
          </div>

          <form className="form zone-editor__reassign" onSubmit={handleFormReassign}>
            <h3>Reasignar paciente</h3>
            <p className="zone-editor__hint">
              Alternativa accesible al arrastre: elige paciente, zona y motivo.
            </p>
            <label htmlFor="reassign-patient">Paciente</label>
            <select
              id="reassign-patient"
              required
              value={formPatientId}
              onChange={(event) => setFormPatientId(event.target.value)}
            >
              <option value="">Selecciona un paciente</option>
              {patients.map((patient) => (
                <option key={patient.id} value={patient.id}>
                  {patient.external_ref}
                </option>
              ))}
            </select>
            <label htmlFor="reassign-zone">Zona de destino</label>
            <select
              id="reassign-zone"
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
            <label htmlFor="reassign-reason">Motivo</label>
            <textarea
              id="reassign-reason"
              required
              rows={3}
              value={formReason}
              onChange={(event) => setFormReason(event.target.value)}
            />
            <button type="submit" disabled={busy}>
              Reasignar
            </button>
          </form>
        </section>
      )}

      {pending && (
        <div className="dialog-backdrop">
          <div
            className="dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="reassign-dialog-title"
          >
            <h2 id="reassign-dialog-title">Confirmar reasignación</h2>
            <p>
              {patientsById.get(pending.patientId)?.external_ref ?? pending.patientId} →{" "}
              {zones.find((zone) => zone.id === pending.targetZoneId)?.name ??
                pending.targetZoneId}
            </p>
            <form
              className="form"
              onSubmit={(event) => {
                event.preventDefault();
                void submitReassign(pending.patientId, pending.targetZoneId, modalReason);
              }}
            >
              <label htmlFor="modal-reason">Motivo</label>
              <textarea
                id="modal-reason"
                required
                rows={3}
                value={modalReason}
                onChange={(event) => setModalReason(event.target.value)}
              />
              <div className="actions">
                <button type="submit">Confirmar</button>
                <button
                  type="button"
                  className="button-secondary"
                  onClick={() => setPending(null)}
                >
                  Cancelar
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </section>
  );
}
