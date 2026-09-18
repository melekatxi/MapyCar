import { ApiError, apiClient } from "./client";
import type {
  ExportFormat,
  ExportRouteResponse,
  JobStatus,
  OptimizeRouteRequest,
  OptimizeRouteResponse,
  RouteComparison,
  RouteDetail,
  StopExecutionReport,
  StopExecutionStatus,
} from "./types";

const DEFAULT_POLL_MS = 1500;
const DEFAULT_MAX_ATTEMPTS = 40;
const TERMINAL_JOB = new Set(["succeeded", "failed", "cancelled"]);

export function getRoute(
  routeId: string,
  organizationId: string,
): Promise<RouteDetail> {
  return apiClient.get(`/routes/${routeId}`, {
    organization_id: organizationId,
  });
}

export function optimizeRoute(params: {
  routeId: string;
  organizationId: string;
  body: OptimizeRouteRequest;
  idempotencyKey: string;
}): Promise<OptimizeRouteResponse> {
  return apiClient.post(`/routes/${params.routeId}/optimize`, params.body, {
    query: { organization_id: params.organizationId },
    idempotencyKey: params.idempotencyKey,
  });
}

export function getRouteComparison(
  routeId: string,
  organizationId: string,
): Promise<RouteComparison> {
  return apiClient.get(`/routes/${routeId}/comparison`, {
    organization_id: organizationId,
  });
}

export function formatStopIfMatch(version: number): string {
  return `"${version}"`;
}

export function reportStopExecution(params: {
  routeId: string;
  stopId: string;
  organizationId: string;
  version: number;
  status: StopExecutionStatus;
  completed_at?: string;
  failure_reason?: string;
}): Promise<StopExecutionReport> {
  const body: {
    status: StopExecutionStatus;
    completed_at?: string;
    failure_reason?: string;
  } = { status: params.status };
  if (params.completed_at) body.completed_at = params.completed_at;
  if (params.failure_reason) body.failure_reason = params.failure_reason;
  return apiClient.patch(`/routes/${params.routeId}/stops/${params.stopId}`, body, {
    query: { organization_id: params.organizationId },
    ifMatch: formatStopIfMatch(params.version),
  });
}

export function latestStopFromConflict(error: ApiError): {
  id: string;
  status: string;
  version: number;
  completed_at: string | null;
  failure_reason: string | null;
  route_status: string;
} | null {
  if (error.code !== "STOP_VERSION_CONFLICT") return null;
  const raw = error.body.errors[0];
  if (!raw || raw.code !== "LATEST_STATE" || raw.id == null || raw.version == null) {
    return null;
  }
  return {
    id: String(raw.id),
    status: String(raw.status ?? ""),
    version: Number(raw.version),
    completed_at: raw.completed_at ?? null,
    failure_reason: raw.failure_reason ?? null,
    route_status: raw.route_status ?? "",
  };
}

export async function reportStopExecutionResilient(params: {
  routeId: string;
  stopId: string;
  organizationId: string;
  version: number;
  status: StopExecutionStatus;
  completed_at?: string;
  failure_reason?: string;
}): Promise<StopExecutionReport> {
  try {
    return await reportStopExecution(params);
  } catch (err) {
    if (!(err instanceof ApiError)) throw err;
    const latest = latestStopFromConflict(err);
    if (latest && latest.status === params.status) {
      return {
        id: latest.id,
        route_id: params.routeId,
        revision_id: "",
        patient_id: "",
        sequence: 0,
        status: latest.status,
        completed_at: latest.completed_at,
        failure_reason: latest.failure_reason,
        version: latest.version,
        route_status: latest.route_status,
      };
    }
    throw err;
  }
}

export function exportRoute(params: {
  routeId: string;
  organizationId: string;
  format: ExportFormat;
  revisionId?: string | null;
  idempotencyKey: string;
}): Promise<ExportRouteResponse> {
  const body: { format: ExportFormat; revision_id?: string } = {
    format: params.format,
  };
  if (params.revisionId) body.revision_id = params.revisionId;
  return apiClient.post(`/routes/${params.routeId}/exports`, body, {
    query: { organization_id: params.organizationId },
    idempotencyKey: params.idempotencyKey,
  });
}

export function getJobArtifact(
  jobId: string,
  organizationId: string,
): Promise<Blob> {
  return apiClient.getBlob(`/jobs/${jobId}/artifact`, {
    organization_id: organizationId,
  });
}

export function getJob(
  jobId: string,
  organizationId: string,
): Promise<JobStatus> {
  return apiClient.get(`/jobs/${jobId}`, {
    organization_id: organizationId,
  });
}

export function jobIsTerminal(job: JobStatus): boolean {
  return TERMINAL_JOB.has(job.status);
}

export async function pollOptimizeJob(
  jobId: string,
  organizationId: string,
  options: {
    intervalMs?: number;
    maxAttempts?: number;
    sleep?: (ms: number) => Promise<void>;
    onTick?: (job: JobStatus) => void;
  } = {},
): Promise<JobStatus> {
  const intervalMs = options.intervalMs ?? DEFAULT_POLL_MS;
  const maxAttempts = options.maxAttempts ?? DEFAULT_MAX_ATTEMPTS;
  const sleep =
    options.sleep ?? ((ms: number) => new Promise((resolve) => setTimeout(resolve, ms)));
  let last: JobStatus | undefined;
  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    last = await getJob(jobId, organizationId);
    options.onTick?.(last);
    if (jobIsTerminal(last)) return last;
    if (attempt < maxAttempts - 1) await sleep(intervalMs);
  }
  if (!last) {
    throw new ApiError({
      type: "https://sofia.example/errors/job-not-ready",
      title: "El trabajo no está listo",
      status: 409,
      code: "JOB_NOT_READY",
      detail: "La optimización no ha terminado",
      request_id: null,
      errors: [],
    });
  }
  return last;
}
