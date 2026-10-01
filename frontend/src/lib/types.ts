export type Intent = "quote_request" | "order_status" | "return_request" | "product_question" | "other" | "unknown";

export interface Health {
  status: "ok" | "degraded";
  db: boolean;
  student: { enabled: boolean; state: "disabled" | "loading" | "ready" | "error"; version: string | null; error: string | null };
  teacher: { configured: boolean; model: string; provider: string; live_mode: string; cached_samples: number };
  router_threshold: number | null;
  admin_configured: boolean;
  notice: string;
}

export interface Sample {
  id: string;
  title: string;
  tags: string[];
  demonstrates: string;
  sender: string;
  subject: string;
  body: string;
  teacher_cached: boolean;
}

export interface StepEvent {
  seq: number;
  step: string;
  status: "running" | "ok" | "error" | "skipped" | "flagged";
  duration_ms?: number | null;
  model?: string | null;
  tokens_in?: number | null;
  tokens_out?: number | null;
  cost_usd?: number;
  retries?: number;
  error?: string | null;
  summary?: string | null;
}

export interface Candidate {
  sku: string;
  name: string;
  category: string;
  score: number;
  reason: string;
  unit: string;
  stock_qty: number;
}

export interface QuoteLine {
  line_no: number;
  item_index: number | null;
  description: string;
  quantity: number | null;
  unit: string | null;
  sku: string | null;
  name: string | null;
  unit_price: number | null;
  list_price: number | null;
  discount_pct: number | null;
  line_total: number | null;
  stock_qty: number | null;
  status: "CONFIDENT" | "NEEDS_REVIEW";
  reason: string | null;
  candidates: Candidate[];
  removed: boolean;
  added_by_user: boolean;
}

export interface ExtractionItem {
  description: string;
  quantity: number | null;
  unit: string | null;
  part_number: string | null;
  compatible_with: string | null;
  reference: string | null;
}

export interface Extraction {
  intent: Intent;
  urgency: "low" | "normal" | "high";
  needed_by: string | null;
  items: ExtractionItem[];
  missing_info: string[];
}

export interface Quote {
  id: string;
  trace_id: string;
  email_id: string;
  status: "pending_approval" | "approved" | "edited" | "rejected" | "sent" | "no_quote";
  intent: Intent;
  created_at: string | null;
  customer: { id: string; name: string; tier: string | null } | null;
  subtotal: number;
  total: number;
  currency: string;
  needs_review: boolean;
  flags: {
    prompt_injection_suspected?: boolean;
    injection_matches?: { rule: string; text: string }[];
    teacher_cached?: boolean;
    admin_corrected?: boolean;
    would_escalate?: boolean;
    degraded?: boolean;
    needs_review_reasons?: string[];
    path?: string;
    confidence?: { score: number; token_prob: number | null; validity: number; completeness: number | null };
    decision?: string;
    sent_at?: string;
    sent_note?: string;
  };
  suggested_action: string | null;
  extraction: Extraction | null;
  student_extraction: Extraction | null;
  extraction_source: string | null;
  sandbox: boolean;
  decided_by: string | null;
  decided_at: string | null;
  lines: QuoteLine[];
  email?: { sender: string; subject: string; body: string; source: string; sample_id: string | null };
}

export interface LineDecision {
  line_no?: number;
  action: "accept" | "change_sku" | "edit_quantity" | "remove" | "add";
  sku?: string;
  quantity?: number;
  description?: string;
  reason?: "misread" | "wrong_part" | "business";
}

export interface DecisionResult {
  status: string;
  decision: string;
  sandbox: boolean;
  corrections: { kind: string; field: string; before: unknown; after: unknown; counts_for_training: boolean; note: string | null }[];
  quote: Quote;
  retrain?: { corrections_pending: number; threshold: number; triggered: boolean };
}

export interface TraceRow {
  id: string;
  created_at: string;
  intent: string | null;
  path: string | null;
  latency_ms: number | null;
  cost_usd: number;
  escalated: boolean;
  status: string;
  quote_id: string | null;
  needs_review: boolean | null;
  model_version: string | null;
  subject: string;
  sender: string;
  source: string;
  injection_suspected: boolean;
}

export interface SpanRow {
  seq: number;
  name: string;
  status: string;
  started_at: string | null;
  duration_ms: number | null;
  model: string | null;
  inputs: unknown;
  outputs: unknown;
  tokens_in: number | null;
  tokens_out: number | null;
  cost_usd: number;
  retries: number;
  error: string | null;
}

export interface TraceDetail extends Omit<TraceRow, "subject" | "sender" | "source" | "needs_review" | "injection_suspected"> {
  email: { sender: string; subject: string; body: string; source: string };
  spans: SpanRow[];
}

export type Metrics = Record<string, number | null | Record<string, number>>;

export interface EvalSystem {
  label: string;
  model: string | null;
  hardware: string | null;
  latency_note: string | null;
  cost_note: string | null;
  created: string | null;
  splits: Record<string, Metrics>;
}

export interface EvalLatest {
  available: boolean;
  message?: string;
  report_dir?: string;
  run?: string;
  created?: string;
  systems?: Record<string, EvalSystem>;
  router_threshold?: number | null;
  how_measured?: string[];
  pricing?: { teacher: { label: string; source: string }; student_cpu: { label: string; source: string } };
  data?: {
    splits: Record<string, unknown> | null;
    verification: { total_checked: number; kept: number; dropped: number; drop_rate: number } | null;
  };
  calibration?: {
    rule: string;
    n: number;
    best_item_f1: number;
    chosen: { threshold: number; item_f1: number; escalation_rate: number; cost_per_1k_usd: number };
    sweep: { threshold: number; item_f1: number; escalation_rate: number; cost_per_1k_usd: number; exact_match_rate: number }[];
  } | null;
}

export interface ModelVersion {
  version: string;
  hf_repo: string | null;
  revision: string | null;
  status: "live" | "candidate" | "rejected" | "retired";
  source: string;
  created_at: string | null;
  promoted_at: string | null;
  metrics: Metrics | null;
  gate: { passed: boolean; checks: { name: string; ok: boolean; detail: string }[]; reasons: string[] } | null;
  notes: string | null;
}

export interface RetrainRun {
  id: number;
  created_at: string | null;
  updated_at: string | null;
  mode: string;
  state: string;
  corrections_count: number;
  candidate_version: string | null;
  gate_result: ModelVersion["gate"];
  reason: string | null;
  log: { ts: string; msg: string }[];
  bundle_available: boolean;
}

export interface RetrainStatus {
  state: string;
  auto_enabled: boolean;
  paused: boolean;
  corrections_pending: number;
  threshold: number;
  active_run: RetrainRun | null;
  runs: RetrainRun[];
}

export interface ModelsResponse {
  live: { state: string; version: string | null; repo: string | null; error: string | null; load_seconds: number | null };
  versions: ModelVersion[];
  retrain: RetrainStatus;
}

export interface CorrectionItemPayload {
  description: string;
  quantity: number | null;
  unit: string | null;
  part_number: string | null;
  compatible_with: string | null;
  reference: "previous_order" | null;
  needs_size_or_spec: boolean;
  needs_equipment_model: boolean;
}

export interface CorrectionPayload {
  intent: Exclude<Intent, "unknown">;
  urgency: "low" | "normal" | "high";
  needed_by: string | null;
  items: CorrectionItemPayload[];
  note?: string;
}

export interface CorrectionResult {
  saved: boolean;
  retrain: { corrections_pending: number; threshold: number; triggered: boolean; error?: string };
  quote: Quote;
}
