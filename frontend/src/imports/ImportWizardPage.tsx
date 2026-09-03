import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { createImport } from "../api/imports";
import { ApiError } from "../api/client";

// Asistente de importación (1.FE.1): carga de fichero, periodo y envío. El mapeo de
// columnas usa por defecto las cabeceras canónicas del backend (id_paciente, direccion...);
// un mapeo personalizado se puede añadir más adelante sin cambiar este flujo.
export function ImportWizardPage() {
  const { organizationId } = useAuth();
  const navigate = useNavigate();
  const [period, setPeriod] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!organizationId || !file) return;
    setSubmitting(true);
    setError(null);
    try {
      const response = await createImport({
        organizationId,
        period,
        file,
        idempotencyKey: crypto.randomUUID(),
      });
      navigate(`/importar/${response.batch_id}`);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.body.detail
          : "No se pudo iniciar la importación",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="page">
      <h1>Importar pacientes</h1>
      <p>
        Sube el listado mensual en formato .csv, .xlsx o .xls (máximo 500 filas).
      </p>
      <form className="card form" onSubmit={handleSubmit}>
        <label htmlFor="period">Periodo (AAAA-MM)</label>
        <input
          id="period"
          type="month"
          required
          value={period}
          onChange={(event) => setPeriod(event.target.value)}
        />
        <label htmlFor="file">Fichero</label>
        <input
          id="file"
          type="file"
          accept=".csv,.xlsx,.xls"
          required
          onChange={(event) => setFile(event.target.files?.[0] ?? null)}
        />
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
        <button type="submit" disabled={submitting || !organizationId}>
          {submitting ? "Subiendo…" : "Subir e iniciar validación"}
        </button>
      </form>
    </section>
  );
}
