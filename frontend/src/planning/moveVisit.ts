import { movePlanVisit } from "../api/planning";
import type { MonthlyPlan, PlanConflict } from "../api/types";

export interface DraggedVisit {
  patientId: string;
  zoneId: string;
  date: string;
}

export type ApplyVisitMoveResult =
  | { ok: true; plan: MonthlyPlan | null; version: number }
  | { ok: false; conflicts: PlanConflict[]; version: number };

export function parseDraggedVisit(
  dataTransfer: DataTransfer | null,
): DraggedVisit | null {
  if (!dataTransfer) return null;
  const raw = dataTransfer.getData("text/plain").trim();
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Partial<DraggedVisit>;
    if (!parsed.patientId || !parsed.zoneId) return null;
    return {
      patientId: parsed.patientId,
      zoneId: parsed.zoneId,
      date: parsed.date ?? "",
    };
  } catch {
    return null;
  }
}

export function dropVisitOnDay(
  dragged: DraggedVisit | null,
  targetDate: string,
): DraggedVisit | null {
  if (!dragged || !targetDate) return null;
  if (dragged.date === targetDate) return null;
  return { patientId: dragged.patientId, zoneId: dragged.zoneId, date: targetDate };
}

export async function applyVisitMove(params: {
  organizationId: string;
  planId: string;
  patientId: string;
  date: string;
  zoneId: string;
  version: number;
}): Promise<ApplyVisitMoveResult> {
  const preview = await movePlanVisit({
    organizationId: params.organizationId,
    planId: params.planId,
    patientId: params.patientId,
    date: params.date,
    zoneId: params.zoneId,
    version: params.version,
  });
  if (preview.conflicts.length > 0) {
    return {
      ok: false,
      conflicts: preview.conflicts,
      version: preview.version,
    };
  }
  const applied = await movePlanVisit({
    organizationId: params.organizationId,
    planId: params.planId,
    patientId: params.patientId,
    date: params.date,
    zoneId: params.zoneId,
    version: params.version,
    confirm: true,
  });
  return { ok: true, plan: applied.plan, version: applied.version };
}
