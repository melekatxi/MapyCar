import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RouteExport } from "./RouteExport";
import * as routingApi from "../api/routing";
import * as exportActions from "./exportActions";
import type { JobStatus, RouteDetail } from "../api/types";

const PUBLISHED: RouteDetail = {
  id: "route-1",
  plan_id: "plan-1",
  organization_id: "org-bizkaia",
  zone_id: "z-a",
  service_date: "2026-09-01",
  assignee_id: "u1",
  status: "published",
  version: 3,
  current_revision: "rev-1",
  revision: 1,
  objective: "time",
  solver_status: "feasible",
  diagnostics: [],
  stops: [{ id: "s1", patient_id: "p1", sequence: 1 }],
};

const DRAFT: RouteDetail = { ...PUBLISHED, status: "draft" };

const JOB_PDF: JobStatus = {
  id: "job-pdf",
  organization_id: "org-bizkaia",
  type: "route.export",
  resource_type: "route",
  resource_id: "route-1",
  status: "succeeded",
  progress: 100,
  attempt: 1,
  error_code: null,
  result_json: { object_key: "exports/a.pdf", format: "pdf" },
  created_at: "2026-09-11T10:00:00Z",
  updated_at: "2026-09-11T10:00:01Z",
};

const JOB_NAV: JobStatus = {
  ...JOB_PDF,
  id: "job-nav",
  result_json: {
    format: "navigation_link",
    navigation_url: "https://www.google.com/maps/dir/43.26,-2.93/43.27,-2.94",
  },
};

describe("RouteExport (3.FE.4)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("descarga PDF y PNG de una ruta publicada", async () => {
    vi.spyOn(routingApi, "exportRoute").mockResolvedValue({
      job_id: "job-pdf",
      status: "queued",
      format: "pdf",
    });
    vi.spyOn(routingApi, "pollOptimizeJob").mockResolvedValue(JOB_PDF);
    vi.spyOn(routingApi, "getJobArtifact").mockResolvedValue(new Blob(["%PDF"]));
    const download = vi.spyOn(exportActions, "triggerDownload").mockImplementation(() => undefined);
    const user = userEvent.setup();

    render(
      <RouteExport organizationId="org-bizkaia" route={PUBLISHED} canEdit />,
    );
    await user.click(screen.getByTestId("export-pdf"));

    await waitFor(() => expect(download).toHaveBeenCalled());
    expect(routingApi.exportRoute).toHaveBeenCalledWith(
      expect.objectContaining({
        routeId: "route-1",
        format: "pdf",
        revisionId: "rev-1",
      }),
    );
    expect(download.mock.calls[0][1]).toBe("ruta-route-1.pdf");
    expect(screen.getByTestId("export-message")).toHaveTextContent("PDF descargado");
  });

  it("pide confirmación de riesgo y copia el enlace de navegación", async () => {
    vi.spyOn(routingApi, "exportRoute").mockResolvedValue({
      job_id: "job-nav",
      status: "queued",
      format: "navigation_link",
    });
    vi.spyOn(routingApi, "pollOptimizeJob").mockResolvedValue(JOB_NAV);
    const copy = vi.spyOn(exportActions, "copyText").mockResolvedValue(undefined);
    const user = userEvent.setup();

    render(
      <RouteExport organizationId="org-bizkaia" route={PUBLISHED} canEdit />,
    );
    await user.click(screen.getByTestId("export-nav"));
    expect(screen.getByRole("dialog")).toHaveTextContent("proveedor externo");
    expect(routingApi.exportRoute).not.toHaveBeenCalled();

    await user.click(screen.getByTestId("export-nav-confirm"));
    await waitFor(() => expect(copy).toHaveBeenCalled());
    expect(copy).toHaveBeenCalledWith(
      "https://www.google.com/maps/dir/43.26,-2.93/43.27,-2.94",
    );
    expect(screen.getByTestId("export-message")).toHaveTextContent("copiado");
  });

  it("no exporta una ruta en borrador", () => {
    render(<RouteExport organizationId="org-bizkaia" route={DRAFT} canEdit />);
    expect(screen.getByTestId("export-unpublished")).toBeInTheDocument();
    expect(screen.getByTestId("export-pdf")).toBeDisabled();
    expect(screen.getByTestId("export-png")).toBeDisabled();
    expect(screen.getByTestId("export-nav")).toBeDisabled();
  });
});
