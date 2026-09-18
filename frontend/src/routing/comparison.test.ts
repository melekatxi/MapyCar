import { describe, expect, it } from "vitest";
import {
  formatCost,
  formatDeviationPct,
  formatDistanceM,
  formatPct,
  formatSeconds,
} from "./comparison";

describe("comparison formatters", () => {
  it("formatea distancia, tiempo, coste y porcentaje de ahorro", () => {
    expect(formatDistanceM(14300)).toBe("14.3 km");
    expect(formatDistanceM(500)).toBe("500 m");
    expect(formatSeconds(1200)).toBe("20 min");
    expect(formatCost(12.5)).toBe("12.50 €");
    expect(formatPct(22)).toBe("−22.0 %");
    expect(formatDeviationPct(15.38)).toBe("+15.4 %");
    expect(formatDeviationPct(-8)).toBe("−8.0 %");
  });
});
