import type { CorrectionPayload, CorrectionResult, DecisionResult, EvalLatest, Health, LineDecision, ModelsResponse, Quote, RetrainStatus, Sample, StepEvent, TraceDetail, TraceRow } from "./types";
import { getAdminToken } from "./admin";

export const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

function headers(json = true, admin = true): HeadersInit {
  const h: Record<string, string> = {};
  if (json) h["Content-Type"] = "application/json";
  const token = admin ? getAdminToken() : null;
  if (token) h["X-Admin-Token"] = token;
  return h;
}

async function request<T>(path: string, init: RequestInit = {}, timeoutMs = 60000): Promise<T> {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(`${API_BASE}${path}`, { ...init, signal: ctrl.signal, headers: { ...headers(!!init.body), ...(init.headers || {}) } });
    if (!res.ok) {
      let msg = res.statusText;
      try {
        const body = await res.json();
        msg = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
      } catch {}
      throw new ApiError(res.status, msg);
    }
    return (await res.json()) as T;
  } finally {
    clearTimeout(t);
  }
}

export const api = {
  health: () => request<Health>("/api/health", {}, 90000),
  samples: () => request<Sample[]>("/api/samples"),
  quote: (id: string) => request<Quote>(`/api/quotes/${id}`),
  decide: (id: string, decision: "approve" | "reject", lines: LineDecision[], note?: string) =>
    request<DecisionResult>(`/api/quotes/${id}/decision`, { method: "POST", body: JSON.stringify({ decision, lines, note }) }),
  correct: (id: string, body: CorrectionPayload) =>
    request<CorrectionResult>(`/api/quotes/${id}/correction`, { method: "POST", body: JSON.stringify(body) }),
  traces: (params = "") => request<TraceRow[]>(`/api/traces${params}`),
  trace: (id: string) => request<TraceDetail>(`/api/traces/${id}`),
  evalLatest: () => request<EvalLatest>("/api/eval/latest"),
  models: () => request<ModelsResponse>("/api/models"),
  retrainStatus: () => request<RetrainStatus>("/api/retrain/status"),
  retrain: (action: "pause" | "resume" | "trigger") =>
    request<unknown>(`/api/retrain/${action}`, { method: "POST", body: JSON.stringify(action === "trigger" ? {} : {}) }),
  rollback: (version: string) => request<unknown>(`/api/models/${version}/rollback`, { method: "POST", body: "{}" }),
  register: (body: { version: string; hf_repo?: string; revision?: string; eval_report: unknown; notes?: string }) =>
    request<{ version: string; promoted: boolean; gate: ModelsResponse["versions"][number]["gate"] }>("/api/models/register", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  async downloadBundle(runId: number) {
    const res = await fetch(`${API_BASE}/api/retrain/runs/${runId}/bundle`, { headers: headers(false) });
    if (!res.ok) throw new ApiError(res.status, "bundle not available");
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `quotedesk-retrain-run-${runId}.zip`;
    a.click();
    URL.revokeObjectURL(url);
  },
};

export interface ProcessHandlers {
  onStep: (e: StepEvent) => void;
  onQuote: (q: Quote) => void;
  onError: (msg: string) => void;
  onDone: (ids: { quote_id: string; trace_id: string }) => void;
}

/** POST an email and stream pipeline events (SSE over fetch, since EventSource cannot POST). */
export async function processEmail(
  body: { sample_id?: string; sender?: string; subject?: string; body?: string },
  h: ProcessHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${API_BASE}/api/quotes/process`, {
    method: "POST",
    headers: { ...headers(true), Accept: "text/event-stream" },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok || !res.body) {
    let msg = `request failed (${res.status})`;
    try {
      const j = await res.json();
      msg = typeof j.detail === "string" ? j.detail : j.error || msg;
    } catch {}
    if (res.status === 429) msg = "Too many requests from your network. Please wait a minute and try again.";
    h.onError(msg);
    return;
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
    let idx: number;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const chunk = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      let event = "message";
      const data: string[] = [];
      for (const line of chunk.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
      }
      if (!data.length) continue;
      let payload: unknown;
      try {
        payload = JSON.parse(data.join("\n"));
      } catch {
        continue;
      }
      if (event === "step") h.onStep(payload as StepEvent);
      else if (event === "quote") h.onQuote(payload as Quote);
      else if (event === "error") h.onError((payload as { message: string }).message);
      else if (event === "done") h.onDone(payload as { quote_id: string; trace_id: string });
    }
  }
}
