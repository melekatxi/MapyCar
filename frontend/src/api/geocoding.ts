import { apiClient } from "./client";
import type { AddressCandidates } from "./types";

export function getAddressCandidates(
  addressId: string,
  organizationId: string,
): Promise<AddressCandidates> {
  return apiClient.get(`/addresses/${addressId}/candidates`, {
    organization_id: organizationId,
  });
}

export function confirmGeocodeSelection(
  addressId: string,
  organizationId: string,
  selection: {
    candidate_index?: number;
    lat?: number;
    lon?: number;
    reason: string;
  },
): Promise<AddressCandidates> {
  return apiClient.post(
    `/addresses/${addressId}/geocode-selection`,
    selection,
    {
      query: { organization_id: organizationId },
    },
  );
}
