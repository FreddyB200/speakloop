export function formatClock(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const two = (n: number) => String(n).padStart(2, "0");
  return h > 0 ? `${h}:${two(m)}:${two(sec)}` : `${two(m)}:${two(sec)}`;
}

export function formatDuration(seconds: number | null): string {
  if (seconds === null) return "n/a";
  return `${(seconds / 60).toFixed(1)} min`;
}

export function formatDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function kindLabel(kind: string): string {
  const text = kind.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function median(values: number[]): number {
  const s = [...values].sort((a, b) => a - b);
  const mid = Math.floor(s.length / 2);
  return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
}

/** Round half to even, matching the Python report (round(130.5) is 130). */
export function roundHalfEven(n: number): number {
  const r = Math.round(n);
  return Math.abs(n % 1) === 0.5 && r % 2 !== 0 ? r - 1 : r;
}
