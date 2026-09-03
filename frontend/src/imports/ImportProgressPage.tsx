import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import {
  commitImport,
  correctImportRow,
  geocodeImport,
  getImportBatch,
  listImportRows,
} from "../api/imports";
import type { ImportBatch, ImportRow } from "../api/types";
import { ApiError } from "../api/client";

const POLL_INTERVAL_MS = 2000;
const IN_PROGRESS_STATUSES = new Set(["uploaded", "validating"]);

// Vista de progreso + tabla de errores (1.FE.2): consulta el estado, muestra conteos y
// permite corregir filas inválidas y confirmar el commit de las filas válidas.
export function ImportProgressPage() {
  const { batchId } = useParams<{ batchId: string }>();
  const { organizationId } = useAuth();
  const [batch, setBatch] = useState<ImportBatch | null>(null);
  const [rows, setRows] = useState<ImportRow[]>([]);
  const [message, setMessage] = useState<string | null>(null);
  const [editingRow, setEditingRow] = useState<number | null>(null);
  const [draftFields, setDraftFields] = useState<Record<string, string>>({});

  const refresh = useCallback(async () => {
    if (!batchId || !organizationId) return;
    const [batchResponse, rowsResponse] = await Promise.all([
      getImportBatch(batchId, organizationId),
      listImportRows(batchId, organizationId),
    ]);
    setBatch(batchResponse);
    setRows(rowsResponse.rows);
  }, [batchId, organizationId]);

  useEffect(() => {
    refresh();
    const interval = setInterval(() => {
      if (batch && !IN_PROGRESS_STATUSES.has(batch.status)) return;
      refresh();
    }, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [refresh, batch]);

  async function handleStartCorrection(row: ImportRow) {
    setEditingRow(row.row_number);
    setDraftFields(
      Object.fromEntries(
        Object.entries(row.fields).map(([key, value]) => [key, value ?? ""]),
      ),
    );
  }

  async function handleSaveCorrection(rowNumber: number) {
    if (!batchId || !organizationId) return;
    await correctImportRow(batchId, organizationId, rowNumber, draftFields);
    setEditingRow(null);
    await refresh();
  }

  async function handleCommit() {
    if (!batchId || !organizationId) return;
    const acceptable = rows
      .filter(
        (row) =>
          row.validation_status === "valid" ||
          row.validation_status === "corrected",
      )
      .map((row) => row.row_number);
    try {
      const result = await commitImport(
        batchId,
        organizationId,
        acceptable,
        crypto.randomUUID(),
      );
      setMessage(
        `Confirmados ${result.committed_patients} pacientes (${result.skipped_rows} filas omitidas).`,
      );
      await refresh();
    } catch (err) {
      setMessage(
        err instanceof ApiError
          ? err.body.detail
          : "No se pudo confirmar la carga",
      );
    }
  }

  async function handleGeocode() {
    if (!batchId || !organizationId) return;
    await geocodeImport(batchId, organizationId);
    setMessage(
      "Geocodificación encolada. Consulta la bandeja de geocodificación en unos segundos.",
    );
  }

  function handleDownloadErrors() {
    const header = "fila,referencia,campo,codigo_error";
    const lines = invalidRows.flatMap((row) =>
      row.errors.map(
        (e) =>
          `${row.row_number},"${row.fields.id_paciente ?? ""}",${e.field},${e.code}`,
      ),
    );
    const csv = [header, ...lines].join("\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `errores-importacion-${batchId}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  }

  if (!batch) return <p className="page">Cargando…</p>;

  const invalidRows = rows.filter((row) => row.validation_status === "invalid");

  return (
    <section className="page">
      <h1>Importación {batch.filename}</h1>
      <p>
        Estado: <strong>{batch.status}</strong> · Total:{" "}
        {batch.counts_json.total ?? "—"} · Válidas:{" "}
        {batch.counts_json.valid ?? "—"} · Inválidas:{" "}
        {batch.counts_json.invalid ?? "—"}
      </p>
      {message && <p className="banner">{message}</p>}

      {invalidRows.length > 0 && (
        <div className="card">
          <h2>Filas con errores ({invalidRows.length})</h2>
          <button type="button" onClick={handleDownloadErrors}>
            Descargar errores (CSV)
          </button>
          <table className="data-table">
            <thead>
              <tr>
                <th>Fila</th>
                <th>Referencia</th>
                <th>Errores</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {invalidRows.map((row) => (
                <tr key={row.row_number}>
                  <td>{row.row_number}</td>
                  <td>{row.fields.id_paciente}</td>
                  <td>
                    {row.errors.map((e) => (
                      <span key={`${e.field}-${e.code}`} className="error-chip">
                        {e.field}: {e.code}
                      </span>
                    ))}
                  </td>
                  <td>
                    {editingRow === row.row_number ? (
                      <>
                        {row.errors.map((e) => (
                          <input
                            key={e.field}
                            aria-label={e.field}
                            value={draftFields[e.field] ?? ""}
                            onChange={(event) =>
                              setDraftFields((prev) => ({
                                ...prev,
                                [e.field]: event.target.value,
                              }))
                            }
                          />
                        ))}
                        <button
                          type="button"
                          onClick={() => handleSaveCorrection(row.row_number)}
                        >
                          Guardar
                        </button>
                      </>
                    ) : (
                      <button
                        type="button"
                        onClick={() => handleStartCorrection(row)}
                      >
                        Corregir
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="actions">
        <button type="button" onClick={handleCommit}>
          Confirmar filas válidas
        </button>
        <button type="button" onClick={handleGeocode}>
          Geocodificar pacientes confirmados
        </button>
      </div>
    </section>
  );
}
