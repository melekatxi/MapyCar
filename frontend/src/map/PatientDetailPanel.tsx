import type { PatientSummary } from "../api/types";

interface Props {
  patient: PatientSummary | null;
  statusLabel: string;
  visitLabel: string;
}

// Detalle de punto (1.FE.6 / RF-08): referencia operativa, municipio/CP y
// día/zona. Sin DailyRoute (Fase 2) día y zona se muestran como "Sin asignar".
// Nunca el nombre real ni la calle exacta (ADR-09). No se filtra por rol field
// (ShareGrant/DailyRoute, Fase 2/4).
export function PatientDetailPanel({
  patient,
  statusLabel,
  visitLabel,
}: Props) {
  if (!patient) {
    return (
      <aside className="detail-panel detail-panel--empty">
        <p>Selecciona un punto del mapa para ver el detalle.</p>
      </aside>
    );
  }

  return (
    <aside className="detail-panel">
      <h2>{patient.external_ref}</h2>
      <dl>
        <dt>Estado de visita</dt>
        <dd>{visitLabel}</dd>
        <dt>Geocodificación</dt>
        <dd>{statusLabel}</dd>
        <dt>Día</dt>
        <dd>{patient.assigned_day ?? "Sin asignar"}</dd>
        <dt>Zona</dt>
        <dd>{patient.assigned_zone ?? "Sin asignar"}</dd>
        <dt>Municipio</dt>
        <dd>{patient.municipality}</dd>
        <dt>Código postal</dt>
        <dd>{patient.postal_code}</dd>
        <dt>Provincia</dt>
        <dd>{patient.province}</dd>
        {patient.confidence !== null && (
          <>
            <dt>Confianza</dt>
            <dd>{(patient.confidence * 100).toFixed(0)}%</dd>
          </>
        )}
      </dl>
    </aside>
  );
}
