import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { OptimizerPage } from "./OptimizerPage";
import * as planningApi from "../api/planning";
import * as patientsApi from "../api/patients";
import * as zoningApi from "../api/zoning";
import * as routingApi from "../api/routing";
import type {
  DailyRouteSummary,
  JobStatus,
  PatientSummary,
  PlanListItem,
  RouteComparison,
  RouteDetail,
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
  service_date: "2026-09-01",
  assignee_id: "u1",
  status: "draft",
  version: 1,
  current_revision: null,
};

const JOB: JobStatus = {
  id: "job-1",
  organization_id: "org-bizkaia",
  type: "route.optimize",
  resource_type: "route",
  resource_id: "route-1",
  status: "succeeded",
  progress: 100,
  attempt: 1,
  error_code: null,
  result_json: {},
  created_at: "2026-09-11T10:00:00Z",
  updated_at: "2026-09-11T10:00:05Z",
};

const DETAIL_BEFORE: RouteDetail = {
  id: "route-1",
  plan_id: "plan-1",
  organization_id: "org-bizkaia",
  zone_id: "z-a",
  service_date: "2026-09-01",
  assignee_id: "u1",
  status: "draft",
  version: 1,
  current_revision: null,
  revision: null,
  objective: null,
  solver_status: null,
  diagnostics: [],
  stops: [],
};

const PATIENT: PatientSummary = {
  id: "p1",
  external_ref: "PAC-001",
  display_ref: "Paciente 001",
  address_id: "a1",
  postal_code: "48001",
  municipality: "Bilbao",
  province: "Bizkaia",
  geocode_status: "matched",
  confidence: 0.9,
  latitude: 43.263,
  longitude: -2.935,
  visit_status: "pending",
};

const COMPARISON: RouteComparison = {
  original: {
    distance_m: 5000,
    travel_seconds: 1000,
    service_seconds: 120,
    estimated_cost: 10,
  },
  optimized: {
    distance_m: 3500,
    travel_seconds: 780,
    service_seconds: 120,
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
  revision_id: "rev-1",
  original_stops: [{ patient_id: "p1", sequence: 1 }],
  optimized_stops: [{ patient_id: "p1", sequence: 1 }],
};

const DETAIL_AFTER: RouteDetail = {
  ...DETAIL_BEFORE,
  version: 2,
  current_revision: "rev-1",
  revision: 1,
  objective: "time",
  solver_status: "feasible",
  status: "ready",
  stops: [
    { id: "s1", patient_id: "p1", sequence: 1 },
    { id: "s2", patient_id: "p2", sequence: 2 },
  ],
};

describe("OptimizerPage (3.FE.1)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("lanza la optimización y muestra el progreso hasta completar", async () => {
    vi.spyOn(planningApi, "listPlans").mockResolvedValue({ plans: [PLAN] });
    vi.spyOn(zoningApi, "listZones").mockResolvedValue({ zones: [ZONE] });
    vi.spyOn(patientsApi, "listPatients").mockResolvedValue({ patients: [PATIENT] });
    vi.spyOn(planningApi, "listPlanRoutes").mockResolvedValue({ routes: [ROUTE] });
    vi.spyOn(routingApi, "getRouteComparison").mockResolvedValue(COMPARISON);
    vi.spyOn(routingApi, "getRoute")
      .mockResolvedValueOnce(DETAIL_BEFORE)
      .mockResolvedValueOnce(DETAIL_AFTER);
    const optimize = vi.spyOn(routingApi, "optimizeRoute").mockResolvedValue({
      job_id: "job-1",
      status: "queued",
      revision_id: null,
    });
    vi.spyOn(routingApi, "pollOptimizeJob").mockImplementation(
      async (_jobId, _org, options) => {
        options?.onTick?.({ ...JOB, status: "queued", progress: 0 });
        options?.onTick?.({ ...JOB, status: "running", progress: 10 });
        options?.onTick?.(JOB);
        return JOB;
      },
    );
    const user = userEvent.setup();

    render(<OptimizerPage />);

    expect(await screen.findByRole("option", { name: /2026-09-01/ })).toBeInTheDocument();
    expect(screen.getByTestId("optimizer-route")).toHaveValue("route-1");
    await user.selectOptions(screen.getByTestId("optimizer-objective"), "time");
    await user.click(screen.getByTestId("optimizer-submit"));

    await waitFor(() => {
      expect(optimize).toHaveBeenCalled();
    });
    const payload = optimize.mock.calls[0][0];
    expect(payload.routeId).toBe("route-1");
    expect(payload.body.objective).toBe("time");
    expect(payload.body.origin).toEqual({ lat: 43.263, lon: -2.935 });
    expect(payload.body.destination).toEqual({ lat: 43.263, lon: -2.935 });
    expect(payload.idempotencyKey).toBeTruthy();

    expect(await screen.findByTestId("optimizer-job-status")).toHaveTextContent("Completada");
    expect(screen.getByTestId("optimizer-progress")).toHaveValue(100);
    expect(screen.getByTestId("optimizer-solver-status")).toHaveTextContent("Factible");
    expect(screen.getByTestId("optimizer-stops").querySelectorAll("li")).toHaveLength(2);
    expect(screen.queryByTestId("optimizer-diagnostics")).not.toBeInTheDocument();
    expect(await screen.findByTestId("comparison-savings-distance")).toHaveTextContent("1.5 km");
    expect(screen.getByTestId("comparison-savings-travel")).toHaveTextContent("−22.0 %");
  });

  it("en un caso inviable muestra el diagnóstico y las acciones sugeridas", async () => {
    const infeasible: RouteDetail = {
      ...DETAIL_AFTER,
      solver_status: "infeasible",
      stops: [],
      diagnostics: [
        {
          code: "ISOLATED_STOP",
          node_indices: [1],
          detail: "La parada 1 no es alcanzable dentro de su ventana.",
          suggested_actions: ["widen window", "drop stop", "split route"],
        },
      ],
    };
    vi.spyOn(planningApi, "listPlans").mockResolvedValue({ plans: [PLAN] });
    vi.spyOn(zoningApi, "listZones").mockResolvedValue({ zones: [ZONE] });
    vi.spyOn(patientsApi, "listPatients").mockResolvedValue({ patients: [PATIENT] });
    vi.spyOn(planningApi, "listPlanRoutes").mockResolvedValue({ routes: [ROUTE] });
    vi.spyOn(routingApi, "getRouteComparison").mockResolvedValue(COMPARISON);
    vi.spyOn(routingApi, "getRoute")
      .mockResolvedValueOnce(DETAIL_BEFORE)
      .mockResolvedValueOnce(infeasible);
    vi.spyOn(routingApi, "optimizeRoute").mockResolvedValue({
      job_id: "job-1",
      status: "queued",
      revision_id: null,
    });
    vi.spyOn(routingApi, "pollOptimizeJob").mockResolvedValue(JOB);
    const user = userEvent.setup();

    render(<OptimizerPage />);
    expect(await screen.findByRole("option", { name: /2026-09-01/ })).toBeInTheDocument();
    await user.click(screen.getByTestId("optimizer-submit"));

    expect(await screen.findByTestId("optimizer-solver-status")).toHaveTextContent("Inviable");
    expect(screen.getByTestId("optimizer-diagnostics")).toHaveTextContent(
      "Parada aislada",
    );
    expect(screen.getByTestId("optimizer-diagnostic-ISOLATED_STOP")).toHaveTextContent(
      "no es alcanzable",
    );
    expect(screen.getByTestId("optimizer-action-widen-window")).toBeEnabled();
    expect(screen.getByTestId("optimizer-action-drop-stop")).toBeEnabled();
    await user.click(screen.getByTestId("optimizer-action-drop-stop"));
    expect(screen.getByTestId("optimizer-action-hint")).toHaveTextContent(
      "Retira una parada",
    );
  });

  it("pide coordenadas de retorno si no se vuelve al origen", async () => {
    vi.spyOn(planningApi, "listPlans").mockResolvedValue({ plans: [PLAN] });
    vi.spyOn(zoningApi, "listZones").mockResolvedValue({ zones: [ZONE] });
    vi.spyOn(patientsApi, "listPatients").mockResolvedValue({ patients: [PATIENT] });
    vi.spyOn(planningApi, "listPlanRoutes").mockResolvedValue({ routes: [ROUTE] });
    vi.spyOn(routingApi, "getRouteComparison").mockResolvedValue(COMPARISON);
    vi.spyOn(routingApi, "getRoute").mockResolvedValue(DETAIL_BEFORE);
    const optimize = vi.spyOn(routingApi, "optimizeRoute").mockResolvedValue({
      job_id: "job-1",
      status: "queued",
      revision_id: null,
    });
    vi.spyOn(routingApi, "pollOptimizeJob").mockResolvedValue(JOB);
    const user = userEvent.setup();

    render(<OptimizerPage />);
    await screen.findByTestId("optimizer-route");
    await user.click(screen.getByTestId("optimizer-return"));
    await user.clear(screen.getByTestId("optimizer-dest-lat"));
    await user.type(screen.getByTestId("optimizer-dest-lat"), "43.27");
    await user.clear(screen.getByTestId("optimizer-dest-lon"));
    await user.type(screen.getByTestId("optimizer-dest-lon"), "-2.94");
    await user.click(screen.getByTestId("optimizer-submit"));

    await waitFor(() => expect(optimize).toHaveBeenCalled());
    expect(optimize.mock.calls[0][0].body.destination).toEqual({
      lat: 43.27,
      lon: -2.94,
    });
  });
});
