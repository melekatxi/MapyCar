// Tipos alineados con los esquemas Pydantic del backend (ver docs/diseno sección 8.3).

export interface Membership {
  organization_id: string;
  role: "admin" | "planner" | "field" | "supervisor";
}

export interface CurrentUser {
  id: string;
  email: string;
  display_name: string;
  memberships: Membership[];
}

export interface ImportBatchCreateResponse {
  batch_id: string;
  job_id: string;
  status: string;
  status_url: string;
}

export interface ImportBatch {
  id: string;
  organization_id: string;
  period: string;
  filename: string;
  status: string;
  counts_json: { total?: number; valid?: number; invalid?: number };
  created_at: string;
}

export interface ImportRowError {
  field: string;
  code: string;
}

export interface ImportRow {
  row_number: number;
  validation_status: "pending" | "valid" | "invalid" | "corrected";
  errors: ImportRowError[];
  fields: Record<string, string | null>;
}

export interface ImportRowsPage {
  rows: ImportRow[];
  next_after_row: number | null;
}

export interface ImportCommitResponse {
  committed_patients: number;
  skipped_rows: number;
}

export type GeocodeStatus =
  | "pending"
  | "matched"
  | "ambiguous"
  | "not_found"
  | "manual";

export type VisitStatus = "pending" | "planned" | "completed";

export interface PatientSummary {
  id: string;
  external_ref: string;
  display_ref: string;
  address_id: string;
  postal_code: string;
  municipality: string;
  province: string;
  geocode_status: GeocodeStatus;
  confidence: number | null;
  latitude: number | null;
  longitude: number | null;
  // RF-07: siempre "pending" hasta Fase 2 (DailyRoute). No inferir rutas.
  visit_status: VisitStatus;
  assigned_day?: string | null;
  assigned_zone?: string | null;
  zone_id?: string | null;
}

export interface LonLat {
  lon: number;
  lat: number;
}

export interface ZoneProposalCreateResponse {
  id: string;
  job_id: string;
  status: string;
}

export interface ZoneProposalCluster {
  cluster_id: string;
  kind: string;
  member_ids: string[];
  centroid: LonLat | null;
}

export interface ZoneProposalAssignment {
  patient_id: string;
  cluster_id: string;
}

export interface ZoneProposalMetrics {
  n_points: number;
  n_clusters: number;
  n_outliers: number;
  max_cluster_size: number;
  max_visits: number;
}

export interface ZoneProposal {
  id: string;
  organization_id: string;
  status: string;
  job_id: string | null;
  params: Record<string, unknown>;
  clusters: ZoneProposalCluster[];
  assignments: ZoneProposalAssignment[];
  outliers: string[];
  metrics: ZoneProposalMetrics | null;
  error_code: string | null;
  created_at: string;
  updated_at: string;
}

export interface ZoneSummary {
  id: string;
  organization_id: string;
  name: string;
  kind: string;
  max_visits: number | null;
  version: number;
  patient_count: number;
  centroid: LonLat | null;
}

export interface ZoneAcceptResponse {
  zones: ZoneSummary[];
  preserved_override_count: number;
}

export interface TeamSummary {
  id: string;
  organization_id: string;
  name: string;
  active: boolean;
}

export interface PlanListItem {
  id: string;
  period: string;
  status: string;
  team_id: string;
}

export interface WorkingDay {
  date: string;
  capacity_visits: number;
  capacity_minutes: number;
  zone_kind: string;
  window_start: string | null;
  window_end: string | null;
}

export interface MonthlyCalendar {
  period: string;
  timezone: string;
  working_days: WorkingDay[];
  skipped_holidays: string[];
}

export interface PlanAssignment {
  patient_id: string;
  date: string;
  zone_id: string;
}

export interface PlanConflict {
  code: string;
  patient_id: string;
  date: string | null;
  zone_id: string | null;
  detail: string;
}

export interface PlanMetrics {
  n_assigned: number;
  n_conflicts: number;
}

export interface MonthlyPlan {
  id: string;
  organization_id: string;
  team_id: string;
  period: string;
  status: string;
  version: number;
  constraints: Record<string, unknown>;
  calendar: MonthlyCalendar;
  assignments: PlanAssignment[];
  conflicts: PlanConflict[];
  metrics: PlanMetrics;
  job_id: string | null;
  created_by: string;
}

export interface PlanCreateResponse {
  id: string;
  organization_id: string;
  team_id: string;
  period: string;
  status: string;
  version: number;
  constraints: Record<string, unknown>;
  created_by: string;
}

export interface PlanGenerateResponse {
  id: string;
  job_id: string;
  status: string;
}

export interface PlanMoveVisitResponse {
  conflicts: PlanConflict[];
  would_apply: boolean;
  version: number;
  plan: MonthlyPlan | null;
}

export interface Candidate {
  lat: number;
  lon: number;
  score: number;
  place_class: string | null;
}

export interface AddressCandidates {
  address_id: string;
  geocode_status: GeocodeStatus;
  candidates: Candidate[];
}
