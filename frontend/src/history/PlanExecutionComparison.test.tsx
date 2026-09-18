import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { PlanExecutionComparison } from "./PlanExecutionComparison";
import type { RouteComparison } from "../api/types";

const BASE: RouteComparison = {
  original: {
    distance_m: 5000,
    travel_seconds: 1000,
    service_seconds: 120,
    estimated_cost: 10,
  },
  optimized: {
    distance_m: 3500,
    travel_seconds: 780,
    service_seconds: 120,
    estimated_cost: 7.2,
  },
  savings: {
    distance_m: 1500,
    travel_seconds: 220,
    estimated_cost: 2.8,
    travel_seconds_pct: 22,
  },
  solver_status: "feasible",
  diagnostics: [],
  revision_id: "rev-1",
  original_stops: [],
  optimized_stops: [],
};

describe("PlanExecutionComparison (4.FE.1)", () => {
  it("indica que no hay ejecución si falta actual", () => {
    render(<PlanExecutionComparison comparison={BASE} />);
    expect(screen.getByTestId("execution-empty")).toBeInTheDocument();
    expect(screen.getByTestId("execution-travel")).toHaveTextContent("—");
  });

  it("muestra desviación de viaje y distancia no reportada", () => {
    render(
      <PlanExecutionComparison
        comparison={{
          ...BASE,
          actual: {
            distance_m: 0,
            travel_seconds: 900,
            service_seconds: 120,
            estimated_cost: 8,
          },
          deviation: {
            distance_m: 0,
            travel_seconds: 120,
            estimated_cost: 0.8,
            travel_seconds_pct: 15.4,
          },
          execution_counts: {
            planned: 3,
            completed: 2,
            failed: 1,
            skipped: 0,
            pending: 0,
          },
        }}
      />,
    );
    expect(screen.getByTestId("execution-counts")).toHaveTextContent("2 completadas");
    expect(screen.getByTestId("execution-distance")).toHaveTextContent("No reportada");
    expect(screen.getByTestId("execution-travel-delta")).toHaveTextContent("2 min");
    expect(screen.getByTestId("execution-travel-delta")).toHaveTextContent("+15.4 %");
  });
});
