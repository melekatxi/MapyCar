import { describe, expect, it, vi, beforeEach } from "vitest";
import { ApiError, apiClient } from "./client";
import { overrideZonePatient, pollZoneProposal } from "./zoning";
import type { ZoneProposal } from "./types";

const NOT_READY = new ApiError({
  type: "https://sofia.example/errors/zone-proposal-not-ready",
  title: "Conflicto",
  status: 409,
  code: "ZONE_PROPOSAL_NOT_READY",
  detail: "La propuesta sigue en estado queued",
  request_id: null,
  errors: [],
});

const READY: ZoneProposal = {
  id: "prop-1",
  organization_id: "org-bizkaia",
  status: "succeeded",
  job_id: "job-1",
  params: { max_visits: 8 },
  clusters: [],
  assignments: [],
  outliers: [],
  metrics: {
    n_points: 2,
    n_clusters: 1,
    n_outliers: 0,
    max_cluster_size: 2,
    max_visits: 8,
  },
  error_code: null,
  created_at: "2026-08-30T00:00:00Z",
  updated_at: "2026-08-30T00:00:01Z",
};

describe("zoning API", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("pollZoneProposal reintenta GET 409 hasta que la propuesta está lista", async () => {
    const get = vi
      .spyOn(apiClient, "get")
      .mockRejectedValueOnce(NOT_READY)
      .mockRejectedValueOnce(NOT_READY)
      .mockResolvedValueOnce(READY);
    const sleep = vi.fn().mockResolvedValue(undefined);

    const result = await pollZoneProposal("prop-1", "org-bizkaia", {
      intervalMs: 10,
      sleep,
    });

    expect(result.status).toBe("succeeded");
    expect(get).toHaveBeenCalledTimes(3);
    expect(sleep).toHaveBeenCalledTimes(2);
  });

  it("overrideZonePatient envía motivo e If-Match de la versión", async () => {
    const put = vi.spyOn(apiClient, "put").mockResolvedValue(undefined);

    await overrideZonePatient({
      organizationId: "org-bizkaia",
      zoneId: "z-b",
      patientId: "p1",
      reason: "más cerca del depósito",
      version: 3,
    });

    expect(put).toHaveBeenCalledWith(
      "/zones/z-b/patients/p1",
      { reason: "más cerca del depósito" },
      {
        query: { organization_id: "org-bizkaia" },
        ifMatch: '"3"',
      },
    );
  });
});
