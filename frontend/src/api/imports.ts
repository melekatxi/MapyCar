import { apiClient } from "./client";
import type {
  ImportBatch,
  ImportBatchCreateResponse,
  ImportCommitResponse,
  ImportRowsPage,
} from "./types";

export function createImport(params: {
  organizationId: string;
  period: string;
  file: File;
  idempotencyKey: string;
}): Promise<ImportBatchCreateResponse> {
  const form = new FormData();
  form.set("organization_id", params.organizationId);
  form.set("period", params.period);
  form.set("file", params.file);
  return apiClient.post("/imports", form, {
    isFormData: true,
    idempotencyKey: params.idempotencyKey,
  });
}

export function getImportBatch(
  batchId: string,
  organizationId: string,
): Promise<ImportBatch> {
  return apiClient.get(`/imports/${batchId}`, {
    organization_id: organizationId,
  });
}

export function listImportRows(
  batchId: string,
  organizationId: string,
  status?: string,
): Promise<ImportRowsPage> {
  return apiClient.get(`/imports/${batchId}/rows`, {
    organization_id: organizationId,
    status,
  });
}

export function correctImportRow(
  batchId: string,
  organizationId: string,
  rowNumber: number,
  fields: Record<string, string>,
) {
  return apiClient.patch(
    `/imports/${batchId}/rows/${rowNumber}`,
    { fields },
    { query: { organization_id: organizationId } },
  );
}

export function commitImport(
  batchId: string,
  organizationId: string,
  acceptedRowNumbers: number[],
  idempotencyKey: string,
): Promise<ImportCommitResponse> {
  return apiClient.post(
    `/imports/${batchId}/commit`,
    { accepted_row_numbers: acceptedRowNumbers },
    { idempotencyKey, query: { organization_id: organizationId } },
  );
}

export function geocodeImport(
  batchId: string,
  organizationId: string,
): Promise<{ job_id: string; status: string }> {
  return apiClient.post(`/imports/${batchId}/geocode`, undefined, {
    query: { organization_id: organizationId },
  });
}
