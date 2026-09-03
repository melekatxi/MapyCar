import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { OperationalMapPage } from "./OperationalMapPage";
import * as patientsApi from "../api/patients";
import type { PatientSummary } from "../api/types";

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

const MATCHED: PatientSummary = {
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
  assigned_zone: null,
};

const PENDING_UNLOCATED: PatientSummary = {
  id: "p2",
  external_ref: "PAC-002",
  display_ref: "Paciente 002",
  address_id: "a2",
  postal_code: "48011",
  municipality: "Bilbao",
  province: "Bizkaia",
  geocode_status: "pending",
  confidence: null,
  latitude: null,
  longitude: null,
  visit_status: "pending",
  assigned_day: null,
  assigned_zone: null,
};

describe("OperationalMapPage (1.QA.1)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("pinta el punto geocodificado y muestra el detalle al seleccionarlo", async () => {
    vi.spyOn(patientsApi, "listPatients").mockResolvedValue({
      patients: [MATCHED, PENDING_UNLOCATED],
    });

    render(<OperationalMapPage />);

    const marker = await screen.findByTestId("map-marker");
    expect(marker).toHaveAttribute("data-lat", "43.263");
    expect(marker).toHaveAttribute("data-lng", "-2.935");
    expect(screen.getByText("PAC-001")).toBeInTheDocument();
    expect(screen.queryByText("PAC-002")).not.toBeInTheDocument();
    expect(
      screen.getByText(/selecciona un punto del mapa/i),
    ).toBeInTheDocument();

    const visitLegend = screen.getByRole("list", { name: "Estado de visita" });
    expect(within(visitLegend).getByText("Pendiente")).toBeInTheDocument();
    expect(within(visitLegend).getByText("Planificada")).toBeInTheDocument();
    expect(within(visitLegend).getByText("Completada")).toBeInTheDocument();
    expect(
      screen.getByRole("list", { name: "Geocodificación" }),
    ).toBeInTheDocument();

    await userEvent.click(marker);

    await waitFor(() => {
      expect(
        screen.getByRole("heading", { name: "PAC-001" }),
      ).toBeInTheDocument();
    });
    const panel = screen.getByRole("heading", { name: "PAC-001" }).closest("aside");
    expect(panel).not.toBeNull();
    expect(within(panel as HTMLElement).getByText("Bilbao")).toBeInTheDocument();
    expect(within(panel as HTMLElement).getByText("48001")).toBeInTheDocument();
    expect(within(panel as HTMLElement).getByText("Geocodificada")).toBeInTheDocument();
    expect(within(panel as HTMLElement).getAllByText("Sin asignar")).toHaveLength(
      2,
    );
    // ADR-09: nunca el nombre real; solo la referencia operativa.
    expect(within(panel as HTMLElement).queryByText("Paciente 001")).not.toBeInTheDocument();
  });
});
