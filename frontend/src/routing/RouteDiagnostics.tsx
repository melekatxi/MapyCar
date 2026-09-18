import { useState } from "react";
import type { RouteDiagnostic } from "../api/types";
import {
  actionHint,
  actionLabel,
  diagnosticTitle,
  uniqueActions,
} from "./diagnostics";

interface RouteDiagnosticsProps {
  diagnostics: RouteDiagnostic[];
  solverStatus: string | null;
}

export function RouteDiagnostics({ diagnostics, solverStatus }: RouteDiagnosticsProps) {
  const [selectedAction, setSelectedAction] = useState<string | null>(null);
  if (diagnostics.length === 0 && solverStatus !== "infeasible") {
    return null;
  }
  const actions = uniqueActions(diagnostics);

  return (
    <div
      className="card optimizer__diagnostics"
      data-testid="optimizer-diagnostics"
      role="alert"
    >
      <h2>Diagnóstico de inviabilidad</h2>
      <p>
        El solver no encontró un tour factible. Las restricciones duras no se relajan
        sin confirmación.
      </p>
      {diagnostics.length === 0 ? (
        <p data-testid="optimizer-diagnostic-empty">Sin detalle adicional del solver.</p>
      ) : (
        <ul className="optimizer__diagnostic-list">
          {diagnostics.map((item, index) => (
            <li
              key={`${item.code}-${index}`}
              data-testid={`optimizer-diagnostic-${item.code}`}
            >
              <strong>{diagnosticTitle(item.code)}</strong>
              {item.node_indices.length > 0 ? (
                <span> (nodos {item.node_indices.join(", ")})</span>
              ) : null}
              <p>{item.detail}</p>
            </li>
          ))}
        </ul>
      )}
      {actions.length > 0 ? (
        <div>
          <h3>Acciones disponibles</h3>
          <div className="actions optimizer__diagnostic-actions">
            {actions.map((action) => (
              <button
                key={action}
                type="button"
                className="button-secondary"
                data-testid={`optimizer-action-${action.replace(/\s+/g, "-")}`}
                onClick={() => setSelectedAction(action)}
              >
                {actionLabel(action)}
              </button>
            ))}
          </div>
          {selectedAction ? (
            <p data-testid="optimizer-action-hint">{actionHint(selectedAction)}</p>
          ) : (
            <p>Elige una acción. No se aplica ningún cambio hasta que confirmes en el formulario.</p>
          )}
          {selectedAction === "split route" ? (
            <p>
              <a href="/planificacion" data-testid="optimizer-action-plan-link">
                Ir a planificación
              </a>
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
