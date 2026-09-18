import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RouteDiagnostics } from "./RouteDiagnostics";
import type { RouteDiagnostic } from "../api/types";

const ISOLATED: RouteDiagnostic = {
  code: "ISOLATED_STOP",
  node_indices: [1],
  detail: "La parada 1 no es alcanzable dentro de su ventana.",
  suggested_actions: ["widen window", "drop stop", "split route"],
};

const WINDOWS: RouteDiagnostic = {
  code: "INCOMPATIBLE_WINDOWS",
  node_indices: [1, 2],
  detail: "Las ventanas de las paradas 1 y 2 no admiten un tour.",
  suggested_actions: ["widen window", "split route", "drop stop", "edit order"],
};

describe("RouteDiagnostics (3.FE.2)", () => {
  it("muestra explicación y acciones de un caso inviable", async () => {
    const user = userEvent.setup();
    render(
      <RouteDiagnostics diagnostics={[ISOLATED]} solverStatus="infeasible" />,
    );

    expect(screen.getByTestId("optimizer-diagnostics")).toHaveTextContent(
      "Diagnóstico de inviabilidad",
    );
    expect(screen.getByTestId("optimizer-diagnostic-ISOLATED_STOP")).toHaveTextContent(
      "Parada aislada",
    );
    expect(screen.getByTestId("optimizer-diagnostic-ISOLATED_STOP")).toHaveTextContent(
      "La parada 1 no es alcanzable dentro de su ventana.",
    );
    expect(screen.getByTestId("optimizer-action-widen-window")).toHaveTextContent(
      "Ampliar ventana",
    );
    expect(screen.getByTestId("optimizer-action-drop-stop")).toHaveTextContent(
      "Retirar parada",
    );
    expect(screen.getByTestId("optimizer-action-split-route")).toHaveTextContent(
      "Dividir ruta",
    );

    await user.click(screen.getByTestId("optimizer-action-widen-window"));
    expect(screen.getByTestId("optimizer-action-hint")).toHaveTextContent(
      "no se relajan solas",
    );
  });

  it("lista las acciones de ventanas incompatibles sin aplicarlas solas", async () => {
    const user = userEvent.setup();
    render(
      <RouteDiagnostics diagnostics={[WINDOWS]} solverStatus="infeasible" />,
    );

    expect(screen.getByTestId("optimizer-diagnostic-INCOMPATIBLE_WINDOWS")).toHaveTextContent(
      "Ventanas incompatibles",
    );
    expect(screen.getByTestId("optimizer-action-edit-order")).toBeEnabled();
    await user.click(screen.getByTestId("optimizer-action-split-route"));
    expect(screen.getByTestId("optimizer-action-hint")).toHaveTextContent(
      "no se divide automáticamente",
    );
    expect(screen.getByTestId("optimizer-action-plan-link")).toHaveAttribute(
      "href",
      "/planificacion",
    );
  });
});
