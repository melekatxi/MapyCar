import { apiClient } from "./client";
import type { PatientSummary } from "./types";

export function listPatients(
  organizationId: string,
): Promise<{ patients: PatientSummary[] }> {
  return apiClient.get("/patients", { organization_id: organizationId });
}
