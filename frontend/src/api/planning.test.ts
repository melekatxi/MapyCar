import { describe, expect, it, vi, beforeEach } from "vitest";
import { ApiError, apiClient } from "./client";
import {
  formatIfMatch,
  movePlanVisit,
  pollPlan,
} from "./planning";
import type { MonthlyPlan } from "./types";

const PLAN: MonthlyPlan = {
  id: "plan-1",
  organization_id: "org-bizkaia",
  team_id: "team-1",
  period: "2026-09",
  status: "draft",
  version: 1,
  constraints: { timezone: "Europe/Madrid" },
  calendar: {
    period: "2026-09",
    timezone: "Europe/Madrid",
    working_days: [],
    skipped_holidays: [],
  },
  assignments: [],
  conflicts: [],
  metrics: { n_assigned: 0, n_conflicts: 0 },
  job_id: "job-1",
  created_by: "u1",
};

describe("planning API", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("formatIfMatch cita la versión como ETag RFC", () => {
    expect(formatIfMatch(2)).toBe('"2"');
  });

  it("movePlanVisit omite confirm en dry-run y envía If-Match", async () => {
    const patch = vi.spyOn(apiClient, "patch").mockResolvedValue({
      conflicts: [],
      would_apply: false,
      version: 1,
      plan: null,
    });

    await movePlanVisit({
      organizationId: "org-bizkaia",
      planId: "plan-1",
      patientId: "p1",
      date: "2026-09-02",
      zoneId: "z-a",
      version: 1,
    });

    expect(patch).toHaveBeenCalledWith(
      "/plans/plan-1/visits/p1",
      { date: "2026-09-02", zone_id: "z-a" },
      {
        query: { organization_id: "org-bizkaia" },
        ifMatch: '"1"',
      },
    );
  });

  it("movePlanVisit envía confirm true al aplicar", async () => {
    const patch = vi.spyOn(apiClient, "patch").mockResolvedValue({
      conflicts: [],
      would_apply: true,
      version: 2,
      plan: PLAN,
    });

    await movePlanVisit({
      organizationId: "org-bizkaia",
      planId: "plan-1",
      patientId: "p1",
      date: "2026-09-02",
      zoneId: "z-a",
      version: 1,
      confirm: true,
    });

    expect(patch).toHaveBeenCalledWith(
      "/plans/plan-1/visits/p1",
      { date: "2026-09-02", zone_id: "z-a", confirm: true },
      {
        query: { organization_id: "org-bizkaia" },
        ifMatch: '"1"',
      },
    );
  });

  it("pollPlan reintenta GET hasta que hay asignaciones", async () => {
    const empty = PLAN;
    const ready: MonthlyPlan = {
      ...PLAN,
      assignments: [{ patient_id: "p1", date: "2026-09-01", zone_id: "z-a" }],
      metrics: { n_assigned: 1, n_conflicts: 0 },
    };
    const get = vi
      .spyOn(apiClient, "get")
      .mockResolvedValueOnce(empty)
      .mockResolvedValueOnce(empty)
      .mockResolvedValueOnce(ready);
    const sleep = vi.fn().mockResolvedValue(undefined);

    const result = await pollPlan("plan-1", "org-bizkaia", {
      intervalMs: 10,
      sleep,
    });

    expect(result.assignments).toHaveLength(1);
    expect(get).toHaveBeenCalledTimes(3);
    expect(sleep).toHaveBeenCalledTimes(2);
  });

  it("pollPlan no enmascara errores que no son de espera", async () => {
    const boom = new ApiError({
      type: "https://sofia.example/errors/forbidden",
      title: "Prohibido",
      status: 403,
      code: "FORBIDDEN_ORGANIZATION",
      detail: "Sin acceso a esta organización",
      request_id: null,
      errors: [],
    });
    vi.spyOn(apiClient, "get").mockRejectedValue(boom);

    await expect(pollPlan("plan-1", "org-bizkaia")).rejects.toBe(boom);
  });
});
