import type { RouteDiagnostic } from "../api/types";

export const DIAGNOSTIC_TITLES: Record<string, string> = {
  INCOMPATIBLE_WINDOWS: "Ventanas incompatibles",
  INSUFFICIENT_SHIFT: "Jornada insuficiente",
  ISOLATED_STOP: "Parada aislada",
};

export const ACTION_LABELS: Record<string, string> = {
  "widen window": "Ampliar ventana",
  "split route": "Dividir ruta",
  "drop stop": "Retirar parada",
  "edit order": "Editar orden",
};

export const ACTION_HINTS: Record<string, string> = {
  "widen window":
    "Amplía la jornada o las ventanas en el formulario y vuelve a optimizar. Las restricciones duras no se relajan solas.",
  "split route":
    "Mueve parte de las visitas a otro día o zona en Planificación. La ruta no se divide automáticamente.",
  "drop stop":
    "Retira una parada del conjunto y vuelve a optimizar. No se excluye ninguna visita sin esa acción.",
  "edit order":
    "Cuando la ruta sea factible podrás reordenar paradas. El orden no se fuerza si el modelo es inviable.",
};

export function diagnosticTitle(code: string): string {
  return DIAGNOSTIC_TITLES[code] ?? code;
}

export function actionLabel(action: string): string {
  return ACTION_LABELS[action] ?? action;
}

export function actionHint(action: string): string {
  return ACTION_HINTS[action] ?? "Confirma el cambio en el formulario y vuelve a optimizar.";
}

export function uniqueActions(diagnostics: RouteDiagnostic[]): string[] {
  const seen = new Set<string>();
  const ordered: string[] = [];
  for (const item of diagnostics) {
    for (const action of item.suggested_actions) {
      if (!seen.has(action)) {
        seen.add(action);
        ordered.push(action);
      }
    }
  }
  return ordered;
}
