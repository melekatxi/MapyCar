import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { ImportProgressPage } from "./ImportProgressPage";
import * as importsApi from "../api/imports";
import type { ImportBatch, ImportRow } from "../api/types";

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

const BATCH: ImportBatch = {
  id: "batch-qa1",
  organization_id: "org-bizkaia",
  period: "2026-08",
  filename: "direcciones-ejemplo-bizkaia.csv",
  status: "requires_correction",
  counts_json: { total: 3, valid: 2, invalid: 1 },
  created_at: "2026-08-01T00:00:00Z",
};

const VALID_ROW: ImportRow = {
  row_number: 1,
  validation_status: "valid",
  errors: [],
  fields: {
    id_paciente: "PAC-001",
    direccion: "Calle Ledesma 12, 3º Izq",
    codigo_postal: "48001",
    municipio: "Bilbao",
    provincia: "Bizkaia",
  },
};

const INVALID_ROW: ImportRow = {
  row_number: 2,
  validation_status: "invalid",
  errors: [{ field: "codigo_postal", code: "INVALID_POSTAL_CODE_FORMAT" }],
  fields: {
    id_paciente: "PAC-002",
    direccion: "Gran Vía Don Diego López de Haro 45, 1º",
    codigo_postal: "XXXXX",
    municipio: "Bilbao",
    provincia: "Bizkaia",
  },
};

describe("ImportProgressPage (1.QA.1)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("corrige una fila inválida, confirma y encola la geocodificación", async () => {
    let rows: ImportRow[] = [VALID_ROW, INVALID_ROW];
    vi.spyOn(importsApi, "getImportBatch").mockResolvedValue(BATCH);
    vi.spyOn(importsApi, "listImportRows").mockImplementation(async () => ({
      rows,
      next_after_row: null,
    }));
    const correct = vi
      .spyOn(importsApi, "correctImportRow")
      .mockImplementation(async (_batch, _org, rowNumber, fields) => {
        rows = rows.map((row) =>
          row.row_number === rowNumber
            ? {
                ...row,
                validation_status: "corrected" as const,
                errors: [],
                fields: { ...row.fields, ...fields },
              }
            : row,
        );
        return rows.find((row) => row.row_number === rowNumber);
      });
    const commit = vi.spyOn(importsApi, "commitImport").mockResolvedValue({
      committed_patients: 2,
      skipped_rows: 0,
    });
    const geocode = vi.spyOn(importsApi, "geocodeImport").mockResolvedValue({
      job_id: "job-geo",
      status: "queued",
    });

    render(
      <MemoryRouter initialEntries={["/importar/batch-qa1"]}>
        <Routes>
          <Route path="/importar/:batchId" element={<ImportProgressPage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByText(/filas con errores \(1\)/i)).toBeInTheDocument();
    expect(screen.getByText("PAC-002")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /corregir/i }));
    const postal = screen.getByLabelText("codigo_postal");
    await userEvent.clear(postal);
    await userEvent.type(postal, "48011");
    await userEvent.click(screen.getByRole("button", { name: /guardar/i }));

    await waitFor(() => {
      expect(correct).toHaveBeenCalledWith(
        "batch-qa1",
        "org-bizkaia",
        2,
        expect.objectContaining({ codigo_postal: "48011" }),
      );
    });
    await waitFor(() => {
      expect(screen.queryByText(/filas con errores/i)).not.toBeInTheDocument();
    });

    await userEvent.click(
      screen.getByRole("button", { name: /confirmar filas válidas/i }),
    );
    await waitFor(() => {
      expect(commit).toHaveBeenCalledWith(
        "batch-qa1",
        "org-bizkaia",
        [1, 2],
        expect.any(String),
      );
    });
    expect(
      await screen.findByText(/confirmados 2 pacientes/i),
    ).toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("button", { name: /geocodificar pacientes confirmados/i }),
    );
    await waitFor(() => {
      expect(geocode).toHaveBeenCalledWith("batch-qa1", "org-bizkaia");
    });
    expect(
      screen.getByText(/geocodificación encolada/i),
    ).toBeInTheDocument();
  });
});
