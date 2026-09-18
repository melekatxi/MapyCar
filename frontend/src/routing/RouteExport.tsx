import { useState } from "react";
import { ApiError } from "../api/client";
import {
  exportRoute,
  getJobArtifact,
  pollOptimizeJob,
} from "../api/routing";
import type { ExportFormat, RouteDetail } from "../api/types";
import { copyText, triggerDownload } from "./exportActions";

const RISK_COPY =
  "El enlace abre Google Maps (proveedor externo). Solo incluye coordenadas, no nombres ni direcciones. Confirma que estás autorizado a enviarlo.";

interface RouteExportProps {
  organizationId: string;
  route: RouteDetail;
  canEdit: boolean;
}

function errorMessage(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.body.detail : fallback;
}

export function RouteExport({ organizationId, route, canEdit }: RouteExportProps) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmNav, setConfirmNav] = useState(false);
  const published = route.status === "published";
  const disabled = busy || !canEdit || !published;

  async function runExport(format: ExportFormat) {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const queued = await exportRoute({
        routeId: route.id,
        organizationId,
        format,
        revisionId: route.current_revision,
        idempotencyKey: crypto.randomUUID(),
      });
      const finished = await pollOptimizeJob(queued.job_id, organizationId);
      if (finished.status !== "succeeded") {
        throw new Error(finished.error_code ?? "La exportación ha fallado");
      }
      if (format === "navigation_link") {
        const url = String(finished.result_json.navigation_url ?? "");
        if (!url) throw new Error("El trabajo no devolvió enlace");
        await copyText(url);
        setMessage("Enlace de navegación copiado (solo coordenadas).");
        return;
      }
      const blob = await getJobArtifact(finished.id, organizationId);
      const filename = format === "pdf" ? `ruta-${route.id}.pdf` : `ruta-${route.id}.png`;
      triggerDownload(blob, filename);
      setMessage(format === "pdf" ? "PDF descargado." : "PNG descargado.");
    } catch (err) {
      setError(errorMessage(err, "No se pudo exportar la ruta"));
    } finally {
      setBusy(false);
      setConfirmNav(false);
    }
  }

  return (
    <div className="card" data-testid="route-export">
      <h2>Exportar</h2>
      <p>
        PDF y PNG se generan en el servidor. El enlace de navegación usa un proveedor
        externo y requiere confirmación.
      </p>
      {!published ? (
        <p data-testid="export-unpublished">Publica la ruta para poder exportarla.</p>
      ) : null}
      <div className="actions">
        <button
          type="button"
          data-testid="export-pdf"
          disabled={disabled}
          onClick={() => runExport("pdf")}
        >
          Descargar PDF
        </button>
        <button
          type="button"
          className="button-secondary"
          data-testid="export-png"
          disabled={disabled}
          onClick={() => runExport("png")}
        >
          Descargar PNG
        </button>
        <button
          type="button"
          className="button-secondary"
          data-testid="export-nav"
          disabled={disabled}
          onClick={() => setConfirmNav(true)}
        >
          Copiar enlace de navegación
        </button>
      </div>
      {message ? <p data-testid="export-message">{message}</p> : null}
      {error ? (
        <p className="form-error" data-testid="export-error">
          {error}
        </p>
      ) : null}

      {confirmNav ? (
        <div className="dialog-backdrop">
          <div
            className="dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="export-nav-title"
          >
            <h2 id="export-nav-title">Confirmar enlace externo</h2>
            <p>{RISK_COPY}</p>
            <div className="actions">
              <button
                type="button"
                data-testid="export-nav-confirm"
                onClick={() => runExport("navigation_link")}
                disabled={busy}
              >
                Confirmar y copiar
              </button>
              <button
                type="button"
                className="button-secondary"
                data-testid="export-nav-cancel"
                onClick={() => setConfirmNav(false)}
                disabled={busy}
              >
                Cancelar
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
