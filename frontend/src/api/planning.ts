import { ApiError, apiClient } from "./client";
import type {
  MonthlyPlan,
  PlanCreateResponse,
  PlanGenerateResponse,
  PlanListItem,
  PlanMoveVisitResponse,
  TeamSummary,
} from "./types";

const DEFAULT_POLL_MS = 1500;
const DEFAULT_MAX_ATTEMPTS = 40;

export const DEFAULT_CALENDAR_CONSTRAINTS = {
  weekday_mask: [1, 2, 3, 4, 5],
  workday_minutes: 480,
  service_minutes: 45,
  timezone: "Europe/Madrid",
  zone_kind: "urban",
} as const;

export function formatIfMatch(version: number): string {
  return `"${version}"`;
}

export function listTeams(
  organizationId: string,
): Promise<{ teams: TeamSummary[] }> {
  return apiClient.get("/teams", { organization_id: organizationId });
}

export function listPlans(
  organizationId: string,
): Promise<{ plans: PlanListItem[] }> {
  return apiClient.get("/plans", { organization_id: organizationId });
}

export function createPlan(body: {
  organization_id: string;
  team_id: string;
  period: string;
  constraints: Record<string, unknown>;
}): Promise<PlanCreateResponse> {
  return apiClient.post("/plans", body);
}

export function generatePlan(
  planId: string,
  organizationId: string,
): Promise<PlanGenerateResponse> {
  return apiClient.post(`/plans/${planId}/generate`, undefined, {
    query: { organization_id: organizationId },
  });
}

export function getPlan(
  planId: string,
  organizationId: string,
): Promise<MonthlyPlan> {
  return apiClient.get(`/plans/${planId}`, {
    organization_id: organizationId,
  });
}

export function movePlanVisit(params: {
  organizationId: string;
  planId: string;
  patientId: string;
  date: string;
  zoneId: string;
  version: number;
  confirm?: boolean;
}): Promise<PlanMoveVisitResponse> {
  const body: Record<string, unknown> = {
    date: params.date,
    zone_id: params.zoneId,
  };
  if (params.confirm === true) {
    body.confirm = true;
  }
  return apiClient.patch(
    `/plans/${params.planId}/visits/${params.patientId}`,
    body,
    {
      query: { organization_id: params.organizationId },
      ifMatch: formatIfMatch(params.version),
    },
  );
}

export function planIsGenerated(plan: MonthlyPlan): boolean {
  return plan.assignments.length > 0 || plan.conflicts.length > 0;
}

export async function pollPlan(
  planId: string,
  organizationId: string,
  options: {
    intervalMs?: number;
    maxAttempts?: number;
    sleep?: (ms: number) => Promise<void>;
    isReady?: (plan: MonthlyPlan) => boolean;
  } = {},
): Promise<MonthlyPlan> {
  const intervalMs = options.intervalMs ?? DEFAULT_POLL_MS;
  const maxAttempts = options.maxAttempts ?? DEFAULT_MAX_ATTEMPTS;
  const sleep =
    options.sleep ?? ((ms: number) => new Promise((resolve) => setTimeout(resolve, ms)));
  const isReady = options.isReady ?? planIsGenerated;
  let last: MonthlyPlan | undefined;
  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    last = await getPlan(planId, organizationId);
    if (isReady(last)) return last;
    if (attempt < maxAttempts - 1) await sleep(intervalMs);
  }
  if (!last) {
    throw new ApiError({
      type: "https://sofia.example/errors/plan-not-ready",
      title: "El plan no está listo",
      status: 409,
      code: "PLAN_NOT_READY",
      detail: "La generación del plan no ha terminado",
      request_id: null,
      errors: [],
    });
  }
  return last;
}
