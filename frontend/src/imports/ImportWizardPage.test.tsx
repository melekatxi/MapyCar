import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { ImportWizardPage } from "./ImportWizardPage";
import * as importsApi from "../api/imports";

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

const BIZKAIA_SLICE = [
  "id_paciente;nombre_referencia;direccion;codigo_postal;municipio;provincia;tipo_zona",
  "PAC-001;Paciente 001;Calle Ledesma 12, 3º Izq;48001;Bilbao;Bizkaia;Urbana",
].join("\n");

describe("ImportWizardPage (1.QA.1)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("acepta CSV, XLSX y XLS (el backend ya parsea .xls)", () => {
    render(
      <MemoryRouter initialEntries={["/importar"]}>
        <Routes>
          <Route path="/importar" element={<ImportWizardPage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.getByLabelText(/fichero/i)).toHaveAttribute(
      "accept",
      ".csv,.xlsx,.xls",
    );
    expect(
      screen.getByText(/formato \.csv, \.xlsx o \.xls/i),
    ).toBeInTheDocument();
  });

  it("sube un recorte CSV ficticio de Bizkaia y navega al progreso", async () => {
    const createImport = vi.spyOn(importsApi, "createImport").mockResolvedValue({
      batch_id: "batch-qa1",
      job_id: "job-qa1",
      status: "uploaded",
      status_url: "/api/v1/imports/batch-qa1",
    });

    render(
      <MemoryRouter initialEntries={["/importar"]}>
        <Routes>
          <Route path="/importar" element={<ImportWizardPage />} />
          <Route
            path="/importar/:batchId"
            element={<p>Progreso de importación batch-qa1</p>}
          />
        </Routes>
      </MemoryRouter>,
    );

    fireEvent.change(screen.getByLabelText(/periodo/i), {
      target: { value: "2026-08" },
    });
    const file = new File([BIZKAIA_SLICE], "direcciones-ejemplo-bizkaia.csv", {
      type: "text/csv",
    });
    const fileInput = screen.getByLabelText(/fichero/i) as HTMLInputElement;
    const fileList = {
      0: file,
      length: 1,
      item: (index: number) => (index === 0 ? file : null),
      *[Symbol.iterator]() {
        yield file;
      },
    } as unknown as FileList;
    Object.defineProperty(fileInput, "files", {
      configurable: true,
      value: fileList,
    });
    fireEvent.change(fileInput);
    fireEvent.submit(fileInput.closest("form") as HTMLFormElement);

    await waitFor(() => {
      expect(createImport).toHaveBeenCalledTimes(1);
    });
    const args = createImport.mock.calls[0][0];
    expect(args.organizationId).toBe("org-bizkaia");
    expect(args.period).toBe("2026-08");
    expect(args.file.name).toBe("direcciones-ejemplo-bizkaia.csv");
    expect(
      await screen.findByText(/progreso de importación batch-qa1/i),
    ).toBeInTheDocument();
  });
});
