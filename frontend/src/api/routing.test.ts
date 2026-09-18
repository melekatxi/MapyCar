import { describe, expect, it, vi, beforeEach } from "vitest";
import { ApiError, apiClient } from "./client";
import {
  exportRoute,
  optimizeRoute,
  pollOptimizeJob,
  reportStopExecution,
  reportStopExecutionResilient,
} from "./routing";
import type { JobStatus } from "./types";

const JOB: JobStatus = {
  id: "job-1",
  organization_id: "org-bizkaia",
  type: "route.optimize",
  resource_type: "route",
  resource_id: "route-1",
  status: "queued",
  progress: 0,
  attempt: 0,
  error_code: null,
  result_json: {},
  created_at: "2026-09-11T10:00:00Z",
  updated_at: "2026-09-11T10:00:00Z",
};

describe("routing API", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("optimizeRoute envía Idempotency-Key y el cuerpo de origen/objetivo", async () => {
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({
      job_id: "job-1",
      status: "queued",
      revision_id: null,
    });

    await optimizeRoute({
      routeId: "route-1",
      organizationId: "org-bizkaia",
      idempotencyKey: "key-1",
      body: {
        objective: "time",
        origin: { lat: 43.263, lon: -2.935 },
        destination: { lat: 43.263, lon: -2.935 },
        service_minutes: 45,
      },
    });

    expect(post).toHaveBeenCalledWith(
      "/routes/route-1/optimize",
      {
        objective: "time",
        origin: { lat: 43.263, lon: -2.935 },
        destination: { lat: 43.263, lon: -2.935 },
        service_minutes: 45,
      },
      {
        query: { organization_id: "org-bizkaia" },
        idempotencyKey: "key-1",
      },
    );
  });

  it("exportRoute envía formato e Idempotency-Key", async () => {
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({
      job_id: "job-exp",
      status: "queued",
      format: "png",
    });

    await exportRoute({
      routeId: "route-1",
      organizationId: "org-bizkaia",
      format: "png",
      idempotencyKey: "exp-1",
    });

    expect(post).toHaveBeenCalledWith(
      "/routes/route-1/exports",
      { format: "png" },
      {
        query: { organization_id: "org-bizkaia" },
        idempotencyKey: "exp-1",
      },
    );
  });

  it("pollOptimizeJob espera hasta succeeded y notifica cada tick", async () => {
    const get = vi
      .spyOn(apiClient, "get")
      .mockResolvedValueOnce({ ...JOB, status: "queued", progress: 0 })
      .mockResolvedValueOnce({ ...JOB, status: "running", progress: 10 })
      .mockResolvedValueOnce({ ...JOB, status: "succeeded", progress: 100 });
    const ticks: string[] = [];

    const finished = await pollOptimizeJob("job-1", "org-bizkaia", {
      sleep: async () => undefined,
      onTick: (job) => {
        ticks.push(`${job.status}:${job.progress}`);
      },
    });

    expect(finished.status).toBe("succeeded");
    expect(finished.progress).toBe(100);
    expect(ticks).toEqual(["queued:0", "running:10", "succeeded:100"]);
    expect(get).toHaveBeenCalledTimes(3);
    expect(get).toHaveBeenCalledWith("/jobs/job-1", {
      organization_id: "org-bizkaia",
    });
  });

  it("reportStopExecution envía If-Match de la parada", async () => {
    const patch = vi.spyOn(apiClient, "patch").mockResolvedValue({
      id: "stop-1",
      route_id: "route-1",
      revision_id: "rev-1",
      patient_id: "p1",
      sequence: 1,
      status: "completed",
      completed_at: "2026-09-18T08:00:00Z",
      failure_reason: null,
      version: 2,
      route_status: "in_progress",
    });

    await reportStopExecution({
      routeId: "route-1",
      stopId: "stop-1",
      organizationId: "org-bizkaia",
      version: 1,
      status: "completed",
    });

    expect(patch).toHaveBeenCalledWith(
      "/routes/route-1/stops/stop-1",
      { status: "completed" },
      {
        query: { organization_id: "org-bizkaia" },
        ifMatch: '"1"',
      },
    );
  });

  it("reportStopExecutionResilient no reintenta si el 409 ya está completada", async () => {
    const conflict = new ApiError({
      type: "https://sofia.example/errors/stop-version-conflict",
      title: "Conflicto",
      status: 409,
      code: "STOP_VERSION_CONFLICT",
      detail: "La parada ha sido modificada",
      request_id: null,
      errors: [
        {
          field: "stop",
          code: "LATEST_STATE",
          id: "stop-1",
          status: "completed",
          version: 2,
          completed_at: "2026-09-18T08:00:00Z",
          failure_reason: null,
          route_status: "in_progress",
        },
      ],
    });
    const patch = vi.spyOn(apiClient, "patch").mockRejectedValue(conflict);

    const reported = await reportStopExecutionResilient({
      routeId: "route-1",
      stopId: "stop-1",
      organizationId: "org-bizkaia",
      version: 1,
      status: "completed",
    });

    expect(patch).toHaveBeenCalledTimes(1);
    expect(reported.status).toBe("completed");
    expect(reported.version).toBe(2);
  });
});
