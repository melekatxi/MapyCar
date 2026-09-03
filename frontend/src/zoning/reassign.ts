import { overrideZonePatient } from "../api/zoning";

export interface ReassignIntent {
  patientId: string;
  targetZoneId: string;
}

export function parseDraggedPatientId(
  dataTransfer: DataTransfer | null,
): string | null {
  if (!dataTransfer) return null;
  const value = dataTransfer.getData("text/plain").trim();
  return value || null;
}

export function dropPatientOnZone(
  patientId: string | null,
  targetZoneId: string,
  currentZoneId: string | null,
): ReassignIntent | null {
  if (!patientId || !targetZoneId) return null;
  if (currentZoneId === targetZoneId) return null;
  return { patientId, targetZoneId };
}

export async function confirmZoneReassign(params: {
  organizationId: string;
  zoneId: string;
  patientId: string;
  reason: string;
  version: number;
}): Promise<void> {
  const reason = params.reason.trim();
  if (!reason) {
    throw new Error("El motivo es obligatorio");
  }
  await overrideZonePatient({ ...params, reason });
}
