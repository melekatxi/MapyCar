import { describe, expect, it, vi, beforeEach } from "vitest";
import { apiClient } from "./client";
import {
  createExternalShare,
  createInternalShare,
  exchangePublicShare,
  listShares,
  revokeShare,
} from "./sharing";

describe("sharing API", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("listShares pide organization_id", async () => {
    const get = vi.spyOn(apiClient, "get").mockResolvedValue({ grants: [] });
    await listShares("route-1", "org-1");
    expect(get).toHaveBeenCalledWith("/routes/route-1/shares", {
      organization_id: "org-1",
    });
  });

  it("createExternalShare envía expires_at e Idempotency-Key", async () => {
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({
      id: "g1",
      token: "tok",
      kind: "external",
    });
    await createExternalShare({
      routeId: "route-1",
      organizationId: "org-1",
      expiresAt: "2026-10-01T23:59:00Z",
      idempotencyKey: "key-ext",
    });
    expect(post).toHaveBeenCalledWith(
      "/routes/route-1/shares",
      { permission: "view", expires_at: "2026-10-01T23:59:00Z" },
      {
        query: { organization_id: "org-1" },
        idempotencyKey: "key-ext",
      },
    );
  });

  it("createInternalShare envía subject y permiso", async () => {
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({ id: "g2", kind: "internal" });
    await createInternalShare({
      routeId: "route-1",
      organizationId: "org-1",
      subjectUserId: "u-2",
      permission: "edit",
      idempotencyKey: "key-int",
    });
    expect(post).toHaveBeenCalledWith(
      "/routes/route-1/shares",
      {
        subject_user_id: "u-2",
        permission: "edit",
        expires_at: undefined,
      },
      {
        query: { organization_id: "org-1" },
        idempotencyKey: "key-int",
      },
    );
  });

  it("revokeShare llama DELETE /shares/{id}", async () => {
    const del = vi.spyOn(apiClient, "delete").mockResolvedValue(undefined);
    await revokeShare("g1", "org-1");
    expect(del).toHaveBeenCalledWith("/shares/g1", { organization_id: "org-1" });
  });

  it("exchangePublicShare envía el token", async () => {
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({
      route_id: "route-1",
      stops: [{ sequence: 1 }],
    });
    await exchangePublicShare("token-value-at-least-32-chars-long");
    expect(post).toHaveBeenCalledWith("/public-shares/exchange", {
      token: "token-value-at-least-32-chars-long",
    });
  });
});
