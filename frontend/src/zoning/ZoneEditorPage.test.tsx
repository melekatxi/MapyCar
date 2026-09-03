import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ZoneEditorPage } from "./ZoneEditorPage";
import * as patientsApi from "../api/patients";
import * as zoningApi from "../api/zoning";
import type { PatientSummary, ZoneProposal, ZoneSummary } from "../api/types";

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

const ZONE_A: ZoneSummary = {
  id: "z-a",
  organization_id: "org-bizkaia",
  name: "cluster-0",
  kind: "urban",
  max_visits: 5,
  version: 2,
  patient_count: 1,
  centroid: { lon: -2.935, lat: 43.263 },
};

const ZONE_B: ZoneSummary = {
  id: "z-b",
  organization_id: "org-bizkaia",
  name: "cluster-1",
  kind: "rural",
  max_visits: 5,
  version: 1,
  patient_count: 1,
  centroid: { lon: -2.94, lat: 43.27 },
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
  assigned_day: null,
  assigned_zone: "cluster-0",
  zone_id: "z-a",
};

const PATIENT_B: PatientSummary = {
  ...PATIENT_A,
  id: "p2",
  external_ref: "PAC-002",
  display_ref: "Paciente 002",
  address_id: "a2",
  latitude: 43.27,
  longitude: -2.94,
  assigned_zone: "cluster-1",
  zone_id: "z-b",
};

const PROPOSAL: ZoneProposal = {
  id: "prop-1",
  organization_id: "org-bizkaia",
  status: "succeeded",
  job_id: "job-1",
  params: { max_visits: 8, target_zones: 2 },
  clusters: [
    {
      cluster_id: "cluster-0",
      kind: "urban",
      member_ids: ["p1"],
      centroid: { lon: -2.935, lat: 43.263 },
    },
    {
      cluster_id: "cluster-1",
      kind: "rural",
      member_ids: ["p2"],
      centroid: { lon: -2.94, lat: 43.27 },
    },
  ],
  assignments: [
    { patient_id: "p1", cluster_id: "cluster-0" },
    { patient_id: "p2", cluster_id: "cluster-1" },
  ],
  outliers: [],
  metrics: {
    n_points: 2,
    n_clusters: 2,
    n_outliers: 0,
    max_cluster_size: 1,
    max_visits: 8,
  },
  error_code: null,
  created_at: "2026-08-30T00:00:00Z",
  updated_at: "2026-08-30T00:00:01Z",
};

function mockPublished(
  zones: ZoneSummary[] = [ZONE_A, ZONE_B],
  patients: PatientSummary[] = [PATIENT_A, PATIENT_B],
) {
  vi.spyOn(zoningApi, "listZones").mockResolvedValue({ zones });
  vi.spyOn(patientsApi, "listPatients").mockResolvedValue({ patients });
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

describe("ZoneEditorPage (2.FE.1)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("el formulario reasigna un paciente con motivo e If-Match", async () => {
    mockPublished();
    const override = vi
      .spyOn(zoningApi, "overrideZonePatient")
      .mockResolvedValue(undefined);
    const user = userEvent.setup();

    render(<ZoneEditorPage />);

    expect(await screen.findByTestId("zone-card-z-a")).toBeInTheDocument();
    expect(screen.getByTestId("capacity-z-a")).toHaveTextContent("1 / 5");
    expect(screen.queryByText("Paciente 001")).not.toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Paciente"), "p1");
    await user.selectOptions(screen.getByLabelText("Zona de destino"), "z-b");
    await user.type(
      screen.getByLabelText(/^Motivo$/),
      "más cerca del depósito",
    );
    await user.click(screen.getByRole("button", { name: "Reasignar" }));

    await waitFor(() => {
      expect(override).toHaveBeenCalledWith({
        organizationId: "org-bizkaia",
        zoneId: "z-b",
        patientId: "p1",
        reason: "más cerca del depósito",
        version: 1,
      });
    });
  });

  it("al soltar un paciente en otra zona pide motivo y llama al mismo PUT", async () => {
    mockPublished();
    const override = vi
      .spyOn(zoningApi, "overrideZonePatient")
      .mockResolvedValue(undefined);
    const user = userEvent.setup();

    render(<ZoneEditorPage />);
    const source = await screen.findByTestId("zone-patient-p1");
    const target = screen.getByTestId("zone-card-z-b");
    dragAndDrop(source, target);

    const dialog = await screen.findByRole("dialog", {
      name: "Confirmar reasignación",
    });
    await user.type(within(dialog).getByLabelText(/^Motivo$/), "caserío más cercano");
    await user.click(within(dialog).getByRole("button", { name: "Confirmar" }));

    await waitFor(() => {
      expect(override).toHaveBeenCalledWith({
        organizationId: "org-bizkaia",
        zoneId: "z-b",
        patientId: "p1",
        reason: "caserío más cercano",
        version: 1,
      });
    });
  });

  it("genera la propuesta, espera el job y permite aceptarla", async () => {
    mockPublished([], [PATIENT_A, PATIENT_B]);
    vi.spyOn(zoningApi, "createZoneProposal").mockResolvedValue({
      id: "prop-1",
      job_id: "job-1",
      status: "queued",
    });
    vi.spyOn(zoningApi, "pollZoneProposal").mockResolvedValue(PROPOSAL);
    const accept = vi.spyOn(zoningApi, "acceptZoneProposal").mockResolvedValue({
      zones: [ZONE_A, ZONE_B],
      preserved_override_count: 0,
    });
    const user = userEvent.setup();

    render(<ZoneEditorPage />);
    fireEvent.change(screen.getByLabelText(/máximo de visitas/i), {
      target: { value: "8" },
    });
    fireEvent.change(screen.getByLabelText(/número de zonas/i), {
      target: { value: "2" },
    });
    await user.click(screen.getByRole("button", { name: "Generar propuesta" }));

    expect(await screen.findByTestId("proposal-capacity-cluster-0")).toHaveTextContent(
      "1 / 8",
    );
    const proposalCards = screen.getByRole("list", { name: "Capacidad de la propuesta" });
    expect(within(proposalCards).getByLabelText("Zona urbana")).toHaveTextContent("Urbana");
    expect(within(proposalCards).getByLabelText("Zona rural")).toHaveTextContent("Rural");
    expect(proposalCards.querySelector(".zone-kind--urban svg")).not.toBeNull();
    expect(proposalCards.querySelector(".zone-kind--rural svg")).not.toBeNull();
    await user.click(screen.getByRole("button", { name: "Aceptar propuesta" }));
    await waitFor(() => {
      expect(accept).toHaveBeenCalledWith("prop-1", "org-bizkaia", false);
    });
  });

  it("muestra iconografía urbana y rural en tarjetas, leyenda y listas (2.FE.3)", async () => {
    mockPublished();
    render(<ZoneEditorPage />);

    const urbanCard = await screen.findByTestId("zone-card-z-a");
    const ruralCard = screen.getByTestId("zone-card-z-b");

    const urbanBadges = within(urbanCard).getAllByLabelText("Zona urbana");
    expect(urbanBadges.length).toBeGreaterThanOrEqual(2);
    expect(urbanBadges[0]).toHaveTextContent("Urbana");
    expect(urbanCard.querySelector(".zone-kind.zone-kind--urban svg")).not.toBeNull();
    const ruralBadges = within(ruralCard).getAllByLabelText("Zona rural");
    expect(ruralBadges.length).toBeGreaterThanOrEqual(2);
    expect(ruralBadges[0]).toHaveTextContent("Rural");
    expect(ruralCard.querySelector(".zone-kind.zone-kind--rural svg")).not.toBeNull();
    expect(urbanCard.querySelector("svg")?.innerHTML).not.toEqual(
      ruralCard.querySelector("svg")?.innerHTML,
    );

    const legend = screen.getByRole("list", { name: "Tipo de zona" });
    expect(within(legend).getByLabelText("Zona urbana")).toBeInTheDocument();
    expect(within(legend).getByLabelText("Zona rural")).toBeInTheDocument();
    expect(legend.querySelector(".zone-kind--urban svg")).not.toBeNull();
    expect(legend.querySelector(".zone-kind--rural svg")).not.toBeNull();

    const urbanPatients = screen.getByRole("list", { name: "Pacientes de cluster-0" });
    const ruralPatients = screen.getByRole("list", { name: "Pacientes de cluster-1" });
    expect(within(urbanPatients).getByText("PAC-001")).toBeInTheDocument();
    expect(within(urbanPatients).getByLabelText("Zona urbana")).toHaveTextContent("Urbana");
    expect(urbanPatients.querySelector(".zone-kind--urban svg")).not.toBeNull();
    expect(within(ruralPatients).getByText("PAC-002")).toBeInTheDocument();
    expect(within(ruralPatients).getByLabelText("Zona rural")).toHaveTextContent("Rural");
    expect(ruralPatients.querySelector(".zone-kind--rural svg")).not.toBeNull();
  });
});
