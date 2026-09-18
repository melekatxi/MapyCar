import type { StopExecutionStatus } from "../api/types";

export const FIELD_OUTBOX_KEY = "sofia_field_outbox";

export interface FieldOutboxItem {
  routeId: string;
  stopId: string;
  organizationId: string;
  version: number;
  status: StopExecutionStatus;
  failure_reason?: string;
}

function readStore(): Storage | null {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

export function loadFieldOutbox(): FieldOutboxItem[] {
  const store = readStore();
  if (!store) return [];
  try {
    const raw = store.getItem(FIELD_OUTBOX_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as FieldOutboxItem[];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function saveFieldOutbox(items: FieldOutboxItem[]): void {
  const store = readStore();
  if (!store) return;
  store.setItem(FIELD_OUTBOX_KEY, JSON.stringify(items));
}

export function enqueueFieldReport(item: FieldOutboxItem): FieldOutboxItem[] {
  const next = loadFieldOutbox().filter((row) => row.stopId !== item.stopId);
  next.push(item);
  saveFieldOutbox(next);
  return next;
}

export function removeFieldReport(stopId: string): FieldOutboxItem[] {
  const next = loadFieldOutbox().filter((row) => row.stopId !== stopId);
  saveFieldOutbox(next);
  return next;
}
