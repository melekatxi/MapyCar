import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HistoryPage } from "./HistoryPage";
import * as historyApi from "../api/history";
import * as routingApi from "../api/routing";
import * as zoningApi from "../api/zoning";
import type { HistoryRoute, RouteComparison, ZoneSummary } from "../api/types";

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
  service_date: "2026-09-08",
  zone_id: "z-a",
  assignee_id: "u1",
  objective: "time",
  stops: [
    {
      sequence: 1,
      patient_id: "p1",
      external_ref: "PAC-001",
      lat: 43.263,
      lon: -2.935,
    },
    {
      sequence: 2,
      patient_id: "p2",
      external_ref: "PAC-002",
      lat: 43.27,
      lon: -2.94,
    },
  ],
};

const COMPARISON: RouteComparison = {
  original: {
    distance_m: 5000,
    travel_seconds: 1000,
    service_seconds: 5400,
    estimated_cost: 10,
  },
  optimized: {
    distance_m: 3500,
    travel_seconds: 780,
    service_seconds: 5400,
    estimated_cost: 7.2,
  },
  savings: {
    distance_m: 1500,
    travel_seconds: 220,
    estimated_cost: 2.8,
    travel_seconds_pct: 22,
  },
  solver_status: "feasible",
  diagnostics: [],
  revision_id: "rev-9",
  original_stops: [],
  optimized_stops: [],
  actual: {
    distance_m: 0,
    travel_seconds: 900,
    service_seconds: 5400,
    estimated_cost: 8.3,
  },
  deviation: {
    distance_m: 0,
    travel_seconds: 120,
    estimated_cost: 1.1,
    travel_seconds_pct: 15.38,
  },
  execution_counts: {
    planned: 2,
    completed: 2,
    failed: 0,
    skipped: 0,
    pending: 0,
  },
};

describe("HistoryPage (4.FE.1)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(zoningApi, "listZones").mockResolvedValue({ zones: [ZONE] });
    vi.spyOn(historyApi, "listHistoryRoutes").mockResolvedValue({
      items: [SNAPSHOT],
      next_cursor: null,
    });
    vi.spyOn(routingApi, "getRouteComparison").mockResolvedValue(COMPARISON);
  });

  it("filtra el histórico y muestra snapshot + plan vs ejecución", async () => {
    const user = userEvent.setup();
    render(<HistoryPage />);

    expect(await screen.findByTestId("history-results")).toBeInTheDocument();
    expect(historyApi.listHistoryRoutes).toHaveBeenCalledWith("org-bizkaia", {});

    await user.selectOptions(screen.getByTestId("history-zone"), "z-a");
    fireEvent.change(screen.getByTestId("history-from"), { target: { value: "2026-09-01" } });
    fireEvent.change(screen.getByTestId("history-to"), { target: { value: "2026-09-30" } });
    await user.type(screen.getByTestId("history-ref"), "PAC-001");
    await user.click(screen.getByTestId("history-search"));

    await waitFor(() => {
      expect(historyApi.listHistoryRoutes).toHaveBeenCalledWith("org-bizkaia", {
        from: "2026-09-01",
        to: "2026-09-30",
        zone: "z-a",
        assignee: undefined,
        patient_ref: "PAC-001",
        cursor: undefined,
      });
    });

    await user.click(screen.getByTestId("history-open-rev-9"));

    expect(await screen.findByTestId("history-snapshot")).toBeInTheDocument();
    expect(screen.getByTestId("snapshot-stop-1")).toHaveTextContent("PAC-001");
    expect(screen.getByTestId("snapshot-stop-2")).toHaveTextContent("PAC-002");
    expect(screen.queryByText("Paciente vivo")).not.toBeInTheDocument();
    expect(screen.getByTestId("snapshot-zone")).toHaveTextContent("Bilbao centro");

    expect(await screen.findByTestId("plan-execution")).toBeInTheDocument();
    expect(screen.getByTestId("execution-counts")).toHaveTextContent("2 completadas");
    expect(screen.getByTestId("execution-distance")).toHaveTextContent("No reportada");
    expect(screen.getByTestId("execution-travel")).toHaveTextContent("15 min");
    expect(screen.getByTestId("execution-travel-delta")).toHaveTextContent("+15.4 %");
    expect(routingApi.getRouteComparison).toHaveBeenCalledWith("route-1", "org-bizkaia");
  });

  it("muestra vacío si el filtro no devuelve snapshots", async () => {
    vi.spyOn(historyApi, "listHistoryRoutes").mockResolvedValue({
      items: [],
      next_cursor: null,
    });
    render(<HistoryPage />);
    expect(await screen.findByTestId("history-empty")).toHaveTextContent(
      "No hay rutas publicadas en este filtro.",
    );
  });
});
