export const money = (v: number | null | undefined, digits = 2) =>
  v == null ? "–" : v.toLocaleString("en-US", { style: "currency", currency: "USD", minimumFractionDigits: digits, maximumFractionDigits: digits });

export const pct = (v: unknown, digits = 1) => (typeof v === "number" ? `${(v * 100).toFixed(digits)}%` : "–");

export const num = (v: unknown, digits = 2) => (typeof v === "number" ? v.toFixed(digits) : "–");

export const ms = (v: number | null | undefined) => (v == null ? "–" : v >= 1000 ? `${(v / 1000).toFixed(1)} s` : `${v} ms`);

export const secs = (v: unknown) => (typeof v === "number" ? (v >= 10 ? `${v.toFixed(0)} s` : `${v.toFixed(1)} s`) : "–");

export const intentLabel: Record<string, string> = {
  quote_request: "Quote request",
  order_status: "Order status",
  return_request: "Return request",
  product_question: "Product question",
  other: "Other",
  unknown: "Unknown",
};

export const pathLabel: Record<string, string> = {
  student: "Small model",
  teacher: "Expert model",
  teacher_cached: "Expert model (cached)",
  student_flagged: "Small model, flagged",
  none: "Manual",
};

export function timeAgo(iso: string | null | undefined) {
  if (!iso) return "–";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return `${Math.max(1, Math.round(s))}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return new Date(iso).toISOString().slice(0, 10);
}
