import { apiClient } from "./client";
import type { HistoryRoutesPage } from "./types";

export interface HistoryRouteFilters {
  from?: string;
  to?: string;
  zone?: string;
  assignee?: string;
  patient_ref?: string;
  cursor?: string;
  limit?: string;
}

export function listHistoryRoutes(
  organizationId: string,
  filters: HistoryRouteFilters = {},
): Promise<HistoryRoutesPage> {
  const query: Record<string, string | undefined> = {
    organization_id: organizationId,
  };
  if (filters.from) query.from = filters.from;
  if (filters.to) query.to = filters.to;
  if (filters.zone) query.zone = filters.zone;
  if (filters.assignee) query.assignee = filters.assignee;
  const patientRef = filters.patient_ref?.trim();
  if (patientRef) query.patient_ref = patientRef;
  if (filters.cursor) query.cursor = filters.cursor;
  if (filters.limit) query.limit = filters.limit;
  return apiClient.get("/history/routes", query);
}
