import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PlanCalendarPage } from "./PlanCalendarPage";
import * as patientsApi from "../api/patients";
import * as planningApi from "../api/planning";
import * as zoningApi from "../api/zoning";
import type {
  MonthlyPlan,
  PatientSummary,
  PlanListItem,
  TeamSummary,
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

const TEAM: TeamSummary = {
  id: "team-1",
  organization_id: "org-bizkaia",
  name: "Equipo Bilbao",
  active: true,
};

const ZONE: ZoneSummary = {
  id: "z-a",
  organization_id: "org-bizkaia",
  name: "cluster-0",
  kind: "urban",
  max_visits: 8,
  version: 1,
  patient_count: 2,
  centroid: { lon: -2.935, lat: 43.263 },
};

const PATIENT_A: PatientSummary = {
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
  assigned_day: "2026-09-01",
  assigned_zone: "cluster-0",
  zone_id: "z-a",
};

const PATIENT_B: PatientSummary = {
  ...PATIENT_A,
  id: "p2",
  external_ref: "PAC-002",
  display_ref: "Paciente 002",
  address_id: "a2",
  assigned_day: "2026-09-02",
};

const PLAN_SUMMARY: PlanListItem = {
  id: "plan-1",
  period: "2026-09",
  status: "draft",
  team_id: "team-1",
};

const PLAN: MonthlyPlan = {
  id: "plan-1",
  organization_id: "org-bizkaia",
  team_id: "team-1",
  period: "2026-09",
  status: "draft",
  version: 1,
  constraints: {
    weekday_mask: [1, 2, 3, 4, 5],
    workday_minutes: 480,
    service_minutes: 45,
    timezone: "Europe/Madrid",
  },
  calendar: {
    period: "2026-09",
    timezone: "Europe/Madrid",
    working_days: [
      {
        date: "2026-09-01",
        capacity_visits: 8,
        capacity_minutes: 480,
        zone_kind: "urban",
        window_start: null,
        window_end: null,
      },
      {
        date: "2026-09-02",
        capacity_visits: 8,
        capacity_minutes: 480,
        zone_kind: "urban",
        window_start: null,
        window_end: null,
      },
    ],
    skipped_holidays: [],
  },
  assignments: [
    { patient_id: "p1", date: "2026-09-01", zone_id: "z-a" },
    { patient_id: "p2", date: "2026-09-02", zone_id: "z-a" },
  ],
  conflicts: [
    {
      code: "ADDRESS_NOT_CONFIRMED",
      patient_id: "p-pending",
      date: null,
      zone_id: "z-a",
      detail: "dirección sin geocodificación confirmada",
    },
  ],
  metrics: { n_assigned: 2, n_conflicts: 1 },
  job_id: "job-1",
  created_by: "u1",
};

function mockCatalog() {
  vi.spyOn(planningApi, "listTeams").mockResolvedValue({ teams: [TEAM] });
  vi.spyOn(planningApi, "listPlans").mockResolvedValue({ plans: [PLAN_SUMMARY] });
  vi.spyOn(zoningApi, "listZones").mockResolvedValue({ zones: [ZONE] });
  vi.spyOn(patientsApi, "listPatients").mockResolvedValue({
    patients: [PATIENT_A, PATIENT_B],
  });
  vi.spyOn(planningApi, "getPlan").mockResolvedValue(PLAN);
}

function dragAndDrop(source: HTMLElement, target: HTMLElement) {
  const store: Record<string, string> = {};
  const dataTransfer = {
    setData: (type: string, value: string) => {
      store[type] = value;
    },
    getData: (type: string) => store[type] ?? "",
    effectAllowed: "move",
    dropEffect: "move",
  };
  fireEvent.dragStart(source, { dataTransfer });
  fireEvent.dragOver(target, { dataTransfer });
  fireEvent.drop(target, { dataTransfer });
}

describe("PlanCalendarPage (2.FE.2)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("el formulario mueve una visita con dry-run y confirmación If-Match", async () => {
    mockCatalog();
    const move = vi
      .spyOn(planningApi, "movePlanVisit")
      .mockResolvedValueOnce({
        conflicts: [],
        would_apply: false,
        version: 1,
        plan: null,
      })
      .mockResolvedValueOnce({
        conflicts: [],
        would_apply: true,
        version: 2,
        plan: {
          ...PLAN,
          version: 2,
          assignments: [
            { patient_id: "p1", date: "2026-09-02", zone_id: "z-a" },
            { patient_id: "p2", date: "2026-09-02", zone_id: "z-a" },
          ],
        },
      });
    const user = userEvent.setup();

    render(<PlanCalendarPage />);
    await user.click(await screen.findByTestId("plan-open-plan-1"));

    expect(await screen.findByTestId("plan-capacity-2026-09-01")).toHaveTextContent(
      "1 / 8",
    );
    expect(screen.getByTestId("plan-conflicts")).toHaveTextContent(
      "ADDRESS_NOT_CONFIRMED",
    );
    expect(screen.getAllByText("Sin asignar").length).toBeGreaterThan(0);
    expect(screen.getByText(/Creado por Planificadora/)).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Paciente"), "p1");
    await user.selectOptions(screen.getByLabelText("Fecha"), "2026-09-02");
    await user.selectOptions(screen.getByLabelText("Zona"), "z-a");
    await user.click(screen.getByRole("button", { name: "Mover visita" }));

    await waitFor(() => {
      expect(move).toHaveBeenCalledTimes(2);
    });
    expect(move).toHaveBeenNthCalledWith(1, {
      organizationId: "org-bizkaia",
      planId: "plan-1",
      patientId: "p1",
      date: "2026-09-02",
      zoneId: "z-a",
      version: 1,
    });
    expect(move).toHaveBeenNthCalledWith(2, {
      organizationId: "org-bizkaia",
      planId: "plan-1",
      patientId: "p1",
      date: "2026-09-02",
      zoneId: "z-a",
      version: 1,
      confirm: true,
    });
  });

  it("si el dry-run tiene conflictos no confirma el movimiento", async () => {
    mockCatalog();
    const move = vi.spyOn(planningApi, "movePlanVisit").mockResolvedValue({
      conflicts: [
        {
          code: "CAPACITY_EXCEEDED",
          patient_id: "p1",
          date: "2026-09-02",
          zone_id: "z-a",
          detail: "capacidad del día superada",
        },
      ],
      would_apply: false,
      version: 1,
      plan: null,
    });
    const user = userEvent.setup();

    render(<PlanCalendarPage />);
    await user.click(await screen.findByTestId("plan-open-plan-1"));
    await screen.findByTestId("plan-visit-p1");

    await user.selectOptions(screen.getByLabelText("Paciente"), "p1");
    await user.selectOptions(screen.getByLabelText("Fecha"), "2026-09-02");
    await user.selectOptions(screen.getByLabelText("Zona"), "z-a");
    await user.click(screen.getByRole("button", { name: "Mover visita" }));

    expect(await screen.findByTestId("move-conflicts")).toHaveTextContent(
      "CAPACITY_EXCEEDED",
    );
    expect(move).toHaveBeenCalledTimes(1);
    expect(move.mock.calls[0]?.[0]).not.toHaveProperty("confirm");
  });

  it("al soltar un chip en otro día llama al mismo PATCH dry-run + confirm", async () => {
    mockCatalog();
    const move = vi
      .spyOn(planningApi, "movePlanVisit")
      .mockResolvedValueOnce({
        conflicts: [],
        would_apply: false,
        version: 1,
        plan: null,
      })
      .mockResolvedValueOnce({
        conflicts: [],
        would_apply: true,
        version: 2,
        plan: PLAN,
      });

    render(<PlanCalendarPage />);
    fireEvent.click(await screen.findByTestId("plan-open-plan-1"));
    const source = await screen.findByTestId("plan-visit-p1");
    const target = screen.getByTestId("plan-day-2026-09-02");
    dragAndDrop(source, target);

    await waitFor(() => {
      expect(move).toHaveBeenCalledTimes(2);
    });
    expect(move).toHaveBeenNthCalledWith(1, {
      organizationId: "org-bizkaia",
      planId: "plan-1",
      patientId: "p1",
      date: "2026-09-02",
      zoneId: "z-a",
      version: 1,
    });
    expect(move).toHaveBeenNthCalledWith(2, {
      organizationId: "org-bizkaia",
      planId: "plan-1",
      patientId: "p1",
      date: "2026-09-02",
      zoneId: "z-a",
      version: 1,
      confirm: true,
    });
  });

  it("muestra iconografía urbana y rural junto al nombre de zona en chips (2.FE.3)", async () => {
    const ruralZone: ZoneSummary = {
      ...ZONE,
      id: "z-b",
      name: "cluster-1",
      kind: "rural",
      centroid: { lon: -2.94, lat: 43.27 },
    };
    mockCatalog();
    vi.spyOn(zoningApi, "listZones").mockResolvedValue({
      zones: [ZONE, ruralZone],
    });
    vi.spyOn(patientsApi, "listPatients").mockResolvedValue({
      patients: [
        PATIENT_A,
        { ...PATIENT_B, assigned_zone: "cluster-1", zone_id: "z-b" },
      ],
    });
    vi.spyOn(planningApi, "getPlan").mockResolvedValue({
      ...PLAN,
      calendar: {
        ...PLAN.calendar,
        working_days: [
          PLAN.calendar.working_days[0]!,
          { ...PLAN.calendar.working_days[1]!, zone_kind: "rural" },
        ],
      },
      assignments: [
        { patient_id: "p1", date: "2026-09-01", zone_id: "z-a" },
        { patient_id: "p2", date: "2026-09-02", zone_id: "z-b" },
      ],
    });
    const user = userEvent.setup();

    render(<PlanCalendarPage />);
    await user.click(await screen.findByTestId("plan-open-plan-1"));

    const urbanChip = await screen.findByTestId("plan-visit-p1");
    const ruralChip = await screen.findByTestId("plan-visit-p2");
    expect(within(urbanChip).getByText("cluster-0")).toBeInTheDocument();
    expect(within(urbanChip).getByLabelText("Zona urbana")).toHaveTextContent("Urbana");
    expect(urbanChip.querySelector(".zone-kind.zone-kind--urban svg")).not.toBeNull();
    expect(within(ruralChip).getByText("cluster-1")).toBeInTheDocument();
    expect(within(ruralChip).getByLabelText("Zona rural")).toHaveTextContent("Rural");
    expect(ruralChip.querySelector(".zone-kind.zone-kind--rural svg")).not.toBeNull();
    expect(urbanChip.querySelector("svg")?.innerHTML).not.toEqual(
      ruralChip.querySelector("svg")?.innerHTML,
    );

    const urbanDay = screen.getByTestId("plan-day-2026-09-01");
    const ruralDay = screen.getByTestId("plan-day-2026-09-02");
    expect(within(urbanDay).getAllByLabelText("Zona urbana").length).toBeGreaterThanOrEqual(2);
    expect(within(ruralDay).getAllByLabelText("Zona rural").length).toBeGreaterThanOrEqual(2);

    await user.selectOptions(screen.getByLabelText("Zona"), "z-b");
    const moveForm = screen.getByRole("button", { name: "Mover visita" }).closest("form");
    expect(moveForm).not.toBeNull();
    expect(within(moveForm as HTMLElement).getByLabelText("Zona rural")).toHaveTextContent(
      "Rural",
    );
    expect(moveForm?.querySelector(".zone-kind--rural svg")).not.toBeNull();
  });

  it("no muestra badge en el chip si listZones no conoce el kind", async () => {
    mockCatalog();
    vi.spyOn(zoningApi, "listZones").mockResolvedValue({ zones: [] });

    render(<PlanCalendarPage />);
    fireEvent.click(await screen.findByTestId("plan-open-plan-1"));

    const chip = await screen.findByTestId("plan-visit-p1");
    expect(within(chip).getByText("z-a")).toBeInTheDocument();
    expect(chip.querySelector(".zone-kind")).toBeNull();
  });
});
