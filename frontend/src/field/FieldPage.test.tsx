import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FieldPage } from "./FieldPage";
import { FIELD_OUTBOX_KEY } from "./outbox";
import * as historyApi from "../api/history";
import * as routingApi from "../api/routing";
import * as zoningApi from "../api/zoning";
import type { HistoryRoute, RouteDetail, ZoneSummary } from "../api/types";

vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({
    organizationId: "org-bizkaia",
    isAuthenticated: true,
    user: {
      id: "u-field",
      email: "campo@bizkaia.example",
      display_name: "Visitadora",
      memberships: [{ organization_id: "org-bizkaia", role: "field" }],
    },
    loading: false,
    login: vi.fn(),
    logout: vi.fn(),
    setOrganizationId: vi.fn(),
  }),
}));

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

const SNAPSHOT: HistoryRoute = {
  route_id: "route-1",
  revision_id: "rev-9",
  revision: 1,
  published_at: "2026-09-18T08:00:00Z",
  service_date: "2026-09-18",
  zone_id: "z-a",
  assignee_id: "u-field",
  objective: "time",
  stops: [],
};

const DETAIL: RouteDetail = {
  id: "route-1",
  plan_id: "plan-1",
  organization_id: "org-bizkaia",
  zone_id: "z-a",
  service_date: "2026-09-18",
  assignee_id: "u-field",
  status: "published",
  version: 2,
  current_revision: "rev-9",
  revision: 1,
  objective: "time",
  solver_status: "feasible",
  diagnostics: [],
  stops: [
    {
      id: "stop-1",
      patient_id: "p1",
      sequence: 1,
      status: "pending",
      version: 1,
      completed_at: null,
      failure_reason: null,
      window_start: "08:00",
      window_end: "09:00",
      lat: 43.263,
      lon: -2.935,
      external_ref: "PAC-001",
    },
  ],
};

describe("FieldPage (4.FE.5)", () => {
  beforeEach(() => {
    sessionStorage.clear();
    vi.restoreAllMocks();
    vi.spyOn(zoningApi, "listZones").mockResolvedValue({ zones: [ZONE] });
    vi.spyOn(historyApi, "listHistoryRoutes").mockResolvedValue({
      items: [SNAPSHOT],
      next_cursor: null,
    });
    vi.spyOn(routingApi, "getRoute").mockResolvedValue(DETAIL);
  });

  it("muestra orden, ventana y seudónimo del snapshot", async () => {
    render(<FieldPage />);
    expect(await screen.findByTestId("field-stop-stop-1")).toBeInTheDocument();
    expect(screen.getByTestId("field-stop-stop-1")).toHaveTextContent("PAC-001");
    expect(screen.getByTestId("field-stop-stop-1")).toHaveTextContent("08:00");
    expect(screen.getByTestId("field-marker-1")).toBeInTheDocument();
  });

  it("tras un corte de red reconecta y no duplica el reporte si ya está completada", async () => {
    const user = userEvent.setup();
    const resilient = vi
      .spyOn(routingApi, "reportStopExecutionResilient")
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce({
        id: "stop-1",
        route_id: "route-1",
        revision_id: "rev-9",
        patient_id: "p1",
        sequence: 1,
        status: "completed",
        completed_at: "2026-09-18T08:05:00Z",
        failure_reason: null,
        version: 2,
        route_status: "in_progress",
      });

    render(<FieldPage />);
    expect(await screen.findByTestId("field-complete-stop-1")).toBeInTheDocument();
    await user.click(screen.getByTestId("field-complete-stop-1"));

    expect(await screen.findByTestId("field-outbox")).toBeInTheDocument();
    expect(sessionStorage.getItem(FIELD_OUTBOX_KEY)).toContain("stop-1");
    expect(sessionStorage.getItem(FIELD_OUTBOX_KEY)).not.toContain("tile");

    await user.click(screen.getByTestId("field-reconnect"));

    await waitFor(() => {
      expect(screen.getByTestId("field-stop-stop-1")).toHaveAttribute("data-status", "completed");
    });
    expect(resilient).toHaveBeenCalledTimes(2);
    expect(screen.queryByTestId("field-outbox")).not.toBeInTheDocument();
    expect(screen.queryByTestId("field-complete-stop-1")).not.toBeInTheDocument();
  });
});
