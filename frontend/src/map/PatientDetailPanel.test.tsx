import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { PatientDetailPanel } from "./PatientDetailPanel";
import type { PatientSummary } from "../api/types";

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
  latitude: 43.26,
  longitude: -2.93,
  visit_status: "pending",
  assigned_day: null,
  assigned_zone: null,
};

describe("PatientDetailPanel", () => {
  it("muestra un mensaje vacío cuando no hay selección", () => {
    render(
      <PatientDetailPanel patient={null} statusLabel="" visitLabel="" />,
    );
    expect(screen.getByText(/selecciona un punto/i)).toBeInTheDocument();
  });

  it("muestra la referencia operativa pero nunca el nombre completo del paciente", () => {
    render(
      <PatientDetailPanel
        patient={PATIENT}
        statusLabel="Geocodificada"
        visitLabel="Pendiente"
      />,
    );
    expect(
      screen.getByRole("heading", { name: "PAC-001" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Bilbao")).toBeInTheDocument();
    expect(screen.getByText("90%")).toBeInTheDocument();
    expect(screen.getByText("Pendiente")).toBeInTheDocument();
    expect(screen.getByText("Geocodificada")).toBeInTheDocument();
    expect(screen.getAllByText("Sin asignar")).toHaveLength(2);
    expect(screen.queryByText("Paciente 001")).not.toBeInTheDocument();
  });
});
