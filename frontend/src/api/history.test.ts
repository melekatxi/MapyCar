import { describe, expect, it, vi, beforeEach } from "vitest";
import { apiClient } from "./client";
import { listHistoryRoutes } from "./history";

describe("history API", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("listHistoryRoutes envía filtros combinados y organization_id", async () => {
    const get = vi.spyOn(apiClient, "get").mockResolvedValue({
      items: [],
      next_cursor: null,
    });

    await listHistoryRoutes("org-bizkaia", {
      from: "2026-09-01",
      to: "2026-09-30",
      zone: "zone-1",
      assignee: "user-1",
      patient_ref: "PAC-001",
    });

    expect(get).toHaveBeenCalledWith("/history/routes", {
      organization_id: "org-bizkaia",
      from: "2026-09-01",
      to: "2026-09-30",
      zone: "zone-1",
      assignee: "user-1",
      patient_ref: "PAC-001",
    });
  });

  it("omite filtros vacíos", async () => {
    const get = vi.spyOn(apiClient, "get").mockResolvedValue({
      items: [],
      next_cursor: null,
    });

    await listHistoryRoutes("org-bizkaia", { from: "", patient_ref: "  " });

    expect(get).toHaveBeenCalledWith("/history/routes", {
      organization_id: "org-bizkaia",
    });
  });
});
