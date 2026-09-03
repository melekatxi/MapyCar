import { describe, expect, it, vi, beforeEach } from "vitest";
import * as zoningApi from "../api/zoning";
import {
  confirmZoneReassign,
  dropPatientOnZone,
  parseDraggedPatientId,
} from "./reassign";

describe("reassign helpers (drag y formulario)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("dropPatientOnZone ignora soltar en la zona actual", () => {
    expect(dropPatientOnZone("p1", "z-a", "z-a")).toBeNull();
    expect(dropPatientOnZone("p1", "z-b", "z-a")).toEqual({
      patientId: "p1",
      targetZoneId: "z-b",
    });
  });

  it("parseDraggedPatientId lee text/plain del dataTransfer", () => {
    const dataTransfer = {
      getData: (type: string) => (type === "text/plain" ? "p1" : ""),
    } as unknown as DataTransfer;
    expect(parseDraggedPatientId(dataTransfer)).toBe("p1");
    expect(parseDraggedPatientId(null)).toBeNull();
  });

  it("confirmZoneReassign exige motivo y llama al PUT versionado", async () => {
    const override = vi
      .spyOn(zoningApi, "overrideZonePatient")
      .mockResolvedValue(undefined);

    await expect(
      confirmZoneReassign({
        organizationId: "org",
        zoneId: "z-b",
        patientId: "p1",
        reason: "   ",
        version: 1,
      }),
    ).rejects.toThrow(/motivo es obligatorio/i);

    expect(override).not.toHaveBeenCalled();

    await confirmZoneReassign({
      organizationId: "org",
      zoneId: "z-b",
      patientId: "p1",
      reason: "  caserío más cercano  ",
      version: 2,
    });

    expect(override).toHaveBeenCalledWith({
      organizationId: "org",
      zoneId: "z-b",
      patientId: "p1",
      reason: "caserío más cercano",
      version: 2,
    });
  });
});
