"use client";

import { StepIcon } from "@/components/bits";
import { ms } from "@/lib/format";
import type { StepEvent } from "@/lib/types";
import { cn } from "@/lib/utils";

export const STEP_LABELS: Record<string, string> = {
  RECEIVED: "Received",
  GUARD: "Safety check",
  EXTRACT: "Read email (small model)",
  VALIDATE: "Check the output",
  NORMALIZE: "Fix derived fields (rules)",
  REPAIR: "Retry (small model)",
  ROUTE: "Confidence check",
  ESCALATE: "Ask the expert model",
  RESOLVE: "Look up parts, stock & prices",
  DRAFT: "Draft the quote",
  PENDING_APPROVAL: "Waiting for a human",
};
const PLACEHOLDER = ["RECEIVED", "GUARD", "EXTRACT", "VALIDATE", "ROUTE", "RESOLVE", "DRAFT", "PENDING_APPROVAL"];

export function Timeline({ steps, running }: { steps: StepEvent[]; running: boolean }) {
  const seen = new Set(steps.map((s) => s.step));
  const pending = running || steps.length === 0 ? PLACEHOLDER.filter((p) => !seen.has(p)) : [];
  return (
    <ol className="relative space-y-1">
      {steps.map((s) => (
        <li
          key={s.seq}
          className={cn(
            "rounded-md border px-3 py-2 transition-colors",
            s.step === "ESCALATE" && s.status !== "skipped" && "border-violet-400/50 bg-violet-500/5",
            s.status === "flagged" && "border-amber-400/50 bg-amber-500/5",
            s.status === "error" && "border-destructive/40 bg-destructive/5",
          )}
        >
          <div className="flex items-center gap-2">
            <StepIcon status={s.status} />
            <span className="text-sm font-medium">{STEP_LABELS[s.step] ?? s.step}</span>
            <span className="tabular ml-auto text-xs text-muted-foreground">{s.status === "running" ? "…" : ms(s.duration_ms)}</span>
          </div>
          {(s.summary || s.model || s.retries || s.error) && s.status !== "running" && (
            <div className="mt-1 space-y-0.5 pl-6 text-xs text-muted-foreground">
              {s.summary && <p>{s.summary}</p>}
              <p className="flex flex-wrap gap-x-3">
                {s.model && <span>model: {s.model}</span>}
                {!!s.retries && <span>retries: {s.retries}</span>}
                {s.tokens_in != null && s.tokens_out != null && (
                  <span>
                    tokens: {s.tokens_in} in / {s.tokens_out} out
                  </span>
                )}
              </p>
              {s.error && <p className="text-destructive">{s.error}</p>}
            </div>
          )}
        </li>
      ))}
      {pending.map((p) => (
        <li key={p} className="flex items-center gap-2 rounded-md border border-dashed px-3 py-2 text-sm text-muted-foreground">
          <StepIcon status="pending" />
          {STEP_LABELS[p]}
        </li>
      ))}
    </ol>
  );
}
