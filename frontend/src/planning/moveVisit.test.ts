import { describe, expect, it, vi, beforeEach } from "vitest";
import * as planningApi from "../api/planning";
import {
  applyVisitMove,
  dropVisitOnDay,
  parseDraggedVisit,
} from "./moveVisit";

describe("moveVisit helpers (drag y formulario)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("dropVisitOnDay ignora soltar en el mismo día", () => {
    const dragged = { patientId: "p1", zoneId: "z-a", date: "2026-09-01" };
    expect(dropVisitOnDay(dragged, "2026-09-01")).toBeNull();
    expect(dropVisitOnDay(dragged, "2026-09-02")).toEqual({
      patientId: "p1",
      zoneId: "z-a",
      date: "2026-09-02",
    });
  });

  it("parseDraggedVisit lee JSON de text/plain", () => {
    const payload = JSON.stringify({
      patientId: "p1",
      zoneId: "z-a",
      date: "2026-09-01",
    });
    const dataTransfer = {
      getData: (type: string) => (type === "text/plain" ? payload : ""),
    } as unknown as DataTransfer;
    expect(parseDraggedVisit(dataTransfer)).toEqual({
      patientId: "p1",
      zoneId: "z-a",
      date: "2026-09-01",
    });
    expect(parseDraggedVisit(null)).toBeNull();
  });

  it("applyVisitMove hace dry-run y confirma si no hay conflictos", async () => {
    const move = vi
      .spyOn(planningApi, "movePlanVisit")
      .mockResolvedValueOnce({
        conflicts: [],
        would_apply: false,
        version: 1,
        plan: null,
      })
      .mockResolvedValueOnce({
        conflicts: [],
        would_apply: true,
        version: 2,
        plan: null,
      });

    const result = await applyVisitMove({
      organizationId: "org",
      planId: "plan-1",
      patientId: "p1",
      date: "2026-09-02",
      zoneId: "z-a",
      version: 1,
    });

    expect(result).toEqual({ ok: true, plan: null, version: 2 });
    expect(move).toHaveBeenNthCalledWith(1, {
      organizationId: "org",
      planId: "plan-1",
      patientId: "p1",
      date: "2026-09-02",
      zoneId: "z-a",
      version: 1,
    });
    expect(move).toHaveBeenNthCalledWith(2, {
      organizationId: "org",
      planId: "plan-1",
      patientId: "p1",
      date: "2026-09-02",
      zoneId: "z-a",
      version: 1,
      confirm: true,
    });
  });

  it("applyVisitMove no confirma si el dry-run devuelve conflictos", async () => {
    const move = vi.spyOn(planningApi, "movePlanVisit").mockResolvedValue({
      conflicts: [
        {
          code: "CAPACITY_EXCEEDED",
          patient_id: "p1",
          date: "2026-09-02",
          zone_id: "z-a",
          detail: "capacidad del día superada",
        },
      ],
      would_apply: false,
      version: 1,
      plan: null,
    });

    const result = await applyVisitMove({
      organizationId: "org",
      planId: "plan-1",
      patientId: "p1",
      date: "2026-09-02",
      zoneId: "z-a",
      version: 1,
    });

    expect(result.ok).toBe(false);
    if (result.ok) throw new Error("expected conflicts");
    expect(result.conflicts[0]?.code).toBe("CAPACITY_EXCEEDED");
    expect(move).toHaveBeenCalledTimes(1);
    expect(move.mock.calls[0]?.[0]).not.toHaveProperty("confirm");
  });
});
