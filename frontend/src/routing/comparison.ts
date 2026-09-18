export function formatDistanceM(meters: number): string {
  const sign = meters < 0 ? "-" : "";
  const abs = Math.abs(meters);
  if (abs >= 1000) {
    return `${sign}${(abs / 1000).toFixed(1)} km`;
  }
  return `${sign}${Math.round(abs)} m`;
}

export function formatSeconds(seconds: number): string {
  const sign = seconds < 0 ? "-" : "";
  const abs = Math.abs(seconds);
  return `${sign}${Math.round(abs / 60)} min`;
}

export function formatCost(value: number): string {
  return `${value.toFixed(2)} €`;
}

export function formatPct(value: number): string {
  const sign = value > 0 ? "−" : value < 0 ? "+" : "";
  return `${sign}${Math.abs(value).toFixed(1)} %`;
}

export function formatDeviationPct(value: number): string {
  if (value === 0) return "0.0 %";
  const sign = value > 0 ? "+" : "−";
  return `${sign}${Math.abs(value).toFixed(1)} %`;
}
