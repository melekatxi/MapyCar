import { apiClient } from "./client";
import type { PublicShareView, ShareGrant, ShareGrantList, SharePermission } from "./types";

export function listShares(
  routeId: string,
  organizationId: string,
): Promise<ShareGrantList> {
  return apiClient.get(`/routes/${routeId}/shares`, {
    organization_id: organizationId,
  });
}

export function createInternalShare(params: {
  routeId: string;
  organizationId: string;
  subjectUserId: string;
  permission: SharePermission;
  expiresAt?: string;
  idempotencyKey: string;
}): Promise<ShareGrant> {
  return apiClient.post(
    `/routes/${params.routeId}/shares`,
    {
      subject_user_id: params.subjectUserId,
      permission: params.permission,
      expires_at: params.expiresAt,
    },
    {
      query: { organization_id: params.organizationId },
      idempotencyKey: params.idempotencyKey,
    },
  );
}

export function createExternalShare(params: {
  routeId: string;
  organizationId: string;
  expiresAt: string;
  idempotencyKey: string;
}): Promise<ShareGrant> {
  return apiClient.post(
    `/routes/${params.routeId}/shares`,
    { permission: "view", expires_at: params.expiresAt },
    {
      query: { organization_id: params.organizationId },
      idempotencyKey: params.idempotencyKey,
    },
  );
}

export function revokeShare(shareId: string, organizationId: string): Promise<void> {
  return apiClient.delete(`/shares/${shareId}`, {
    organization_id: organizationId,
  });
}

export function exchangePublicShare(token: string): Promise<PublicShareView> {
  return apiClient.post("/public-shares/exchange", { token });
}
