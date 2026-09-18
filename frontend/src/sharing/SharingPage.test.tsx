import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SharingPage } from "./SharingPage";
import * as planningApi from "../api/planning";
import * as sharingApi from "../api/sharing";
import * as zoningApi from "../api/zoning";
import type {
  DailyRouteSummary,
  PlanListItem,
  PublicShareView,
  ShareGrant,
  ZoneSummary,
} from "../api/types";

vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({
    organizationId: "org-bizkaia",
    isAuthenticated: true,
    user: {
      id: "u1",
      email: "planner@bizkaia.example",
      display_name: "Planificadora",
      memberships: [{ organization_id: "org-bizkaia", role: "planner" }],
    },
    loading: false,
    login: vi.fn(),
    logout: vi.fn(),
    setOrganizationId: vi.fn(),
  }),
}));

const PLAN: PlanListItem = {
  id: "plan-1",
  period: "2026-09",
  status: "published",
  team_id: "team-1",
};

const ZONE: ZoneSummary = {
  id: "z-a",
  organization_id: "org-bizkaia",
  name: "Bilbao centro",
  kind: "urban",
  max_visits: 8,
  version: 1,
  patient_count: 2,
  centroid: { lon: -2.935, lat: 43.263 },
};

const ROUTE: DailyRouteSummary = {
  id: "route-1",
  plan_id: "plan-1",
  organization_id: "org-bizkaia",
  zone_id: "z-a",
  service_date: "2026-09-08",
  assignee_id: "u1",
  status: "published",
  version: 2,
  current_revision: "rev-1",
};

const GRANT: ShareGrant = {
  id: "grant-ext-1",
  route_id: "route-1",
  subject_user_id: null,
  permission: "view",
  expires_at: "2026-10-01T23:59:00Z",
  revoked_at: null,
  created_by: "u1",
  last_accessed_at: null,
  kind: "external",
  token: null,
};

const PREVIEW: PublicShareView = {
  route_id: "route-1",
  service_date: "2026-09-08",
  stop_count: 2,
  stops: [{ sequence: 1 }, { sequence: 2 }],
  permission: "view",
  expires_at: "2026-10-01T23:59:00Z",
};

describe("SharingPage (4.FE.2)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(planningApi, "listPlans").mockResolvedValue({ plans: [PLAN] });
    vi.spyOn(planningApi, "listPlanRoutes").mockResolvedValue({ routes: [ROUTE] });
    vi.spyOn(zoningApi, "listZones").mockResolvedValue({ zones: [ZONE] });
  });

  it("crea un enlace externo, muestra la vista minimizada y lo revoca", async () => {
    const user = userEvent.setup();
    const list = vi
      .spyOn(sharingApi, "listShares")
      .mockResolvedValueOnce({ grants: [] })
      .mockResolvedValueOnce({ grants: [GRANT] })
      .mockResolvedValueOnce({ grants: [] });
    const create = vi.spyOn(sharingApi, "createExternalShare").mockResolvedValue({
      ...GRANT,
      token: "token-shown-only-once-value-32chars",
    });
    const exchange = vi.spyOn(sharingApi, "exchangePublicShare").mockResolvedValue(PREVIEW);
    const revoke = vi.spyOn(sharingApi, "revokeShare").mockResolvedValue(undefined);

    render(<SharingPage />);

    expect(await screen.findByTestId("share-empty")).toBeInTheDocument();
    const submit = screen.getByTestId("share-external-submit");
    expect(submit).toBeDisabled();

    await user.click(screen.getByTestId("share-risk"));
    expect(submit).toBeEnabled();
    await user.click(submit);

    expect(await screen.findByTestId("share-token")).toHaveTextContent(
      "token-shown-only-once-value-32chars",
    );
    expect(screen.getByTestId("share-preview")).toBeInTheDocument();
    expect(screen.getByTestId("share-preview-stops")).toHaveTextContent("Parada 1");
    expect(screen.getByTestId("share-preview-stops")).toHaveTextContent("Parada 2");
    expect(screen.queryByText("PAC-001")).not.toBeInTheDocument();
    expect(create).toHaveBeenCalledTimes(1);
    expect(exchange).toHaveBeenCalledWith("token-shown-only-once-value-32chars");

    await user.click(screen.getByTestId("share-revoke-grant-ext-1"));
    await waitFor(() => {
      expect(screen.getByTestId("share-empty")).toBeInTheDocument();
    });
    expect(revoke).toHaveBeenCalledWith("grant-ext-1", "org-bizkaia");
    expect(list).toHaveBeenCalledTimes(3);
  });
});
