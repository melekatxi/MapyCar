import { ApiError, apiClient } from "./client";
import type {
  ZoneAcceptResponse,
  ZoneProposal,
  ZoneProposalCreateResponse,
  ZoneSummary,
} from "./types";

const DEFAULT_POLL_MS = 1500;
const DEFAULT_MAX_ATTEMPTS = 40;

export function formatIfMatch(version: number): string {
  return `"${version}"`;
}

export function listZones(
  organizationId: string,
): Promise<{ zones: ZoneSummary[] }> {
  return apiClient.get("/zones", { organization_id: organizationId });
}

export function createZoneProposal(body: {
  organization_id: string;
  max_visits: number;
  target_zones?: number;
}): Promise<ZoneProposalCreateResponse> {
  return apiClient.post("/zone-proposals", body);
}

export function getZoneProposal(
  proposalId: string,
  organizationId: string,
): Promise<ZoneProposal> {
  return apiClient.get(`/zone-proposals/${proposalId}`, {
    organization_id: organizationId,
  });
}

export async function pollZoneProposal(
  proposalId: string,
  organizationId: string,
  options: {
    intervalMs?: number;
    maxAttempts?: number;
    sleep?: (ms: number) => Promise<void>;
  } = {},
): Promise<ZoneProposal> {
  const intervalMs = options.intervalMs ?? DEFAULT_POLL_MS;
  const maxAttempts = options.maxAttempts ?? DEFAULT_MAX_ATTEMPTS;
  const sleep =
    options.sleep ?? ((ms: number) => new Promise((resolve) => setTimeout(resolve, ms)));
  let lastError: unknown;
  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    try {
      return await getZoneProposal(proposalId, organizationId);
    } catch (err) {
      lastError = err;
      if (err instanceof ApiError && err.status === 409) {
        await sleep(intervalMs);
        continue;
      }
      throw err;
    }
  }
  throw lastError instanceof Error
    ? lastError
    : new Error("La propuesta no está lista");
}

export function acceptZoneProposal(
  proposalId: string,
  organizationId: string,
  resetOverrides = false,
): Promise<ZoneAcceptResponse> {
  return apiClient.post(`/zone-proposals/${proposalId}/accept`, undefined, {
    query: {
      organization_id: organizationId,
      ...(resetOverrides ? { reset_overrides: "true" } : {}),
    },
  });
}

export function overrideZonePatient(params: {
  organizationId: string;
  zoneId: string;
  patientId: string;
  reason: string;
  version: number;
}): Promise<void> {
  return apiClient.put(
    `/zones/${params.zoneId}/patients/${params.patientId}`,
    { reason: params.reason },
    {
      query: { organization_id: params.organizationId },
      ifMatch: formatIfMatch(params.version),
    },
  );
}
