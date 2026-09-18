import { describe, expect, it, beforeEach } from "vitest";
import {
  FIELD_OUTBOX_KEY,
  enqueueFieldReport,
  loadFieldOutbox,
  removeFieldReport,
  saveFieldOutbox,
} from "./outbox";

describe("field outbox", () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  it("guarda reportes pendientes sin teselas", () => {
    enqueueFieldReport({
      routeId: "route-1",
      stopId: "stop-1",
      organizationId: "org-1",
      version: 1,
      status: "completed",
    });
    const stored = sessionStorage.getItem(FIELD_OUTBOX_KEY);
    expect(stored).toContain("stop-1");
    expect(stored).not.toContain("tile");
    expect(loadFieldOutbox()).toHaveLength(1);
  });

  it("sustituye el mismo stop y permite borrar tras éxito", () => {
    enqueueFieldReport({
      routeId: "route-1",
      stopId: "stop-1",
      organizationId: "org-1",
      version: 1,
      status: "completed",
    });
    enqueueFieldReport({
      routeId: "route-1",
      stopId: "stop-1",
      organizationId: "org-1",
      version: 1,
      status: "failed",
      failure_reason: "no abre",
    });
    expect(loadFieldOutbox()).toEqual([
      {
        routeId: "route-1",
        stopId: "stop-1",
        organizationId: "org-1",
        version: 1,
        status: "failed",
        failure_reason: "no abre",
      },
    ]);
    removeFieldReport("stop-1");
    expect(loadFieldOutbox()).toEqual([]);
  });

  it("saveFieldOutbox persiste la cola", () => {
    saveFieldOutbox([]);
    expect(loadFieldOutbox()).toEqual([]);
  });
});
