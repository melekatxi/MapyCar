import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { RouteComparison } from "./RouteComparison";
import type { PatientSummary, RouteComparison as RouteComparisonData } from "../api/types";

const PATIENTS: PatientSummary[] = [
  {
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
  },
  {
    id: "p2",
    external_ref: "PAC-002",
    display_ref: "Paciente 002",
    address_id: "a2",
    postal_code: "48001",
    municipality: "Bilbao",
    province: "Bizkaia",
    geocode_status: "matched",
    confidence: 0.9,
    latitude: 43.27,
    longitude: -2.94,
    visit_status: "pending",
  },
];

const COMPARISON: RouteComparisonData = {
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
  original_stops: [
    { patient_id: "p1", sequence: 1 },
    { patient_id: "p2", sequence: 2 },
  ],
  optimized_stops: [
    { patient_id: "p2", sequence: 1 },
    { patient_id: "p1", sequence: 2 },
  ],
};

describe("RouteComparison (3.FE.3)", () => {
  it("muestra el ahorro estimado y el orden numerado", () => {
    render(<RouteComparison comparison={COMPARISON} patients={PATIENTS} />);

    expect(screen.getByTestId("comparison-savings-distance")).toHaveTextContent("1.5 km");
    expect(screen.getByTestId("comparison-savings-travel")).toHaveTextContent("4 min");
    expect(screen.getByTestId("comparison-savings-travel")).toHaveTextContent("−22.0 %");
    expect(screen.getByTestId("comparison-savings-cost")).toHaveTextContent("2.80 €");
    expect(screen.getByTestId("comparison-marker-optimized-1")).toHaveAttribute(
      "data-patient",
      "p2",
    );
    expect(screen.getByTestId("comparison-marker-original-1")).toHaveAttribute(
      "data-patient",
      "p1",
    );
    expect(screen.getByText("Orden optimizado (numerado)")).toBeInTheDocument();
  });
});
