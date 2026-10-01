"use client";

import Link from "next/link";
import { use, useEffect, useState } from "react";
import { ArrowLeft } from "lucide-react";
import { JsonView, PathBadge, Stat, StepIcon } from "@/components/bits";
import { STEP_LABELS } from "@/components/playground/timeline";
import { ServerStatus } from "@/components/server-status";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api } from "@/lib/api";
import { intentLabel, money, ms } from "@/lib/format";
import type { TraceDetail } from "@/lib/types";
import { useBackend } from "@/lib/use-backend";
import { cn } from "@/lib/utils";

export default function TracePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const backend = useBackend();
  const [t, setT] = useState<TraceDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (backend.state === "ready") api.trace(id).then(setT).catch((e) => setError(String(e)));
  }, [backend.state, id]);

  const total = t ? Math.max(1, t.spans.reduce((a, s) => a + (s.duration_ms ?? 0), 0)) : 1;
  const starts = t ? t.spans.map((_, i) => t.spans.slice(0, i).reduce((a, s) => a + (s.duration_ms ?? 0), 0)) : [];

  return (
    <div className="mx-auto max-w-6xl px-4 py-8">
      <Link href="/traces" className="mb-3 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="size-4" /> All traces
      </Link>
      <ServerStatus state={backend.state} elapsed={backend.elapsed} retry={backend.retry} />
      {error && <p className="text-sm text-destructive">{error}</p>}
      {t && (
        <div className="space-y-6">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-xl font-semibold">{t.email.subject || "(no subject)"}</h1>
            <PathBadge path={t.path} />
          </div>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
            <Stat label="Intent" value={t.intent ? intentLabel[t.intent] ?? t.intent : "–"} />
            <Stat label="Total latency" value={ms(t.latency_ms)} />
            <Stat label="Cost" value={money(t.cost_usd, 5)} hint="teacher at published price; student estimated" />
            <Stat label="Escalated" value={t.escalated ? "yes" : "no"} />
            <Stat label="Student version" value={t.model_version ?? "–"} />
          </div>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Waterfall</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {t.spans.map((s, i) => {
                const left = (starts[i] / total) * 100;
                const width = Math.max(0.8, ((s.duration_ms ?? 0) / total) * 100);
                return (
                  <details key={s.seq} className="group rounded-md border">
                    <summary className="flex cursor-pointer list-none items-center gap-3 px-3 py-2">
                      <StepIcon status={s.status} />
                      <span className="w-52 shrink-0 text-sm">{STEP_LABELS[s.name] ?? s.name}</span>
                      <div className="relative hidden h-3 flex-1 rounded bg-muted md:block">
                        <div
                          className={cn(
                            "absolute top-0 h-3 rounded",
                            s.name === "ESCALATE" ? "bg-violet-500" : s.status === "error" ? "bg-destructive" : "bg-primary",
                          )}
                          style={{ left: `${left}%`, width: `${width}%` }}
                        />
                      </div>
                      <span className="tabular ml-auto w-20 text-right text-xs text-muted-foreground">{ms(s.duration_ms)}</span>
                    </summary>
                    <div className="space-y-2 border-t p-3 text-xs">
                      <div className="flex flex-wrap gap-x-4 gap-y-1 text-muted-foreground">
                        <span>status: {s.status}</span>
                        {s.model && <span>model: {s.model}</span>}
                        {s.tokens_in != null && <span>tokens in: {s.tokens_in}</span>}
                        {s.tokens_out != null && <span>tokens out: {s.tokens_out}</span>}
                        {!!s.cost_usd && <span>cost: {money(s.cost_usd, 5)}</span>}
                        {!!s.retries && <span>retries: {s.retries}</span>}
                      </div>
                      {s.error && <p className="text-destructive">{s.error}</p>}
                      <JsonView label="inputs" value={s.inputs} />
                      <JsonView label="outputs" value={s.outputs} defaultOpen />
                    </div>
                  </details>
                );
              })}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Email</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-xs text-muted-foreground">{t.email.sender}</p>
              <pre className="mt-2 text-sm whitespace-pre-wrap">{t.email.body}</pre>
              {t.quote_id && (
                <p className="mt-3 text-xs text-muted-foreground">
                  quote id <span className="font-mono">{t.quote_id}</span>
                </p>
              )}
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
