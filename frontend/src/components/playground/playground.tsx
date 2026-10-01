"use client";

import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { CheckCircle2, Inbox, Loader2, PenLine, Play } from "lucide-react";
import { ServerStatus } from "@/components/server-status";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { getAdminToken } from "@/lib/admin";
import { api, processEmail } from "@/lib/api";
import type { CorrectionResult, Quote, RetrainStatus, Sample, StepEvent } from "@/lib/types";
import { useBackend } from "@/lib/use-backend";
import { cn } from "@/lib/utils";
import { QuoteView } from "./quote-view";
import { Timeline } from "./timeline";

type Source = { kind: "sample"; id: string } | { kind: "custom" };

export function Playground() {
  const params = useSearchParams();
  const backend = useBackend();
  const [samples, setSamples] = useState<Sample[]>([]);
  const [source, setSource] = useState<Source | null>(null);
  const [custom, setCustom] = useState({ sender: "Andre Brennan <andre.brennan@pinecrest-mech.example>", subject: "", body: "" });
  const [steps, setSteps] = useState<StepEvent[]>([]);
  const [quote, setQuote] = useState<Quote | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [isAdmin, setIsAdmin] = useState(false);
  const [retrain, setRetrain] = useState<Pick<RetrainStatus, "corrections_pending" | "threshold"> | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [quoteVersion, setQuoteVersion] = useState(0);
  const abortRef = useRef<AbortController | null>(null);
  const autoRan = useRef(false);

  useEffect(() => {
    const sync = () => setIsAdmin(!!getAdminToken());
    sync();
    window.addEventListener("quotedesk-admin", sync);
    return () => window.removeEventListener("quotedesk-admin", sync);
  }, []);

  useEffect(() => {
    if (backend.state === "ready" && isAdmin) api.retrainStatus().then(setRetrain).catch(() => {});
  }, [backend.state, isAdmin]);

  const onCorrected = useCallback((res: CorrectionResult) => {
    setQuote(res.quote);
    setQuoteVersion((v) => v + 1);
    setRetrain({ corrections_pending: res.retrain.corrections_pending, threshold: res.retrain.threshold });
    setNotice(
      res.retrain.triggered
        ? `Correction saved. Corrections ${res.retrain.corrections_pending}/${res.retrain.threshold}: threshold reached, the training bundle is ready on the Models page.`
        : `Correction saved. Corrections ${res.retrain.corrections_pending}/${res.retrain.threshold}.`,
    );
  }, []);

  useEffect(() => {
    if (backend.state === "ready") api.samples().then(setSamples).catch((e) => setError(String(e)));
  }, [backend.state]);

  const run = useCallback(async (src: Source, customBody?: typeof custom) => {
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setSource(src);
    setSteps([]);
    setQuote(null);
    setNotice(null);
    setError(null);
    setRunning(true);
    try {
      await processEmail(
        src.kind === "sample" ? { sample_id: src.id } : { sender: customBody!.sender, subject: customBody!.subject, body: customBody!.body },
        {
          onStep: (s) => setSteps((prev) => [...prev.filter((p) => p.seq !== s.seq), s].sort((a, b) => a.seq - b.seq)),
          onQuote: setQuote,
          onError: setError,
          onDone: () => {},
        },
        ctrl.signal,
      );
    } catch (e) {
      if (!ctrl.signal.aborted) setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (abortRef.current === ctrl) setRunning(false);
    }
  }, []);

  useEffect(() => {
    const id = params.get("sample");
    if (!autoRan.current && id && backend.state === "ready" && samples.some((s) => s.id === id)) {
      autoRan.current = true;
      run({ kind: "sample", id });
    }
  }, [params, backend.state, samples, run]);

  const selected = source?.kind === "sample" ? samples.find((s) => s.id === source.id) : null;

  return (
    <div className="mx-auto max-w-[1400px] px-4 py-6">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-2xl font-semibold">Playground</h1>
          <p className="text-sm text-muted-foreground">Pick an email. Watch each step run live. Review the draft and approve it.</p>
        </div>
        {isAdmin && (
          <a href="/models" className="flex items-center gap-2 rounded-md border px-3 py-1.5 text-sm hover:bg-muted/50">
            <span className="text-muted-foreground">Corrections</span>
            <span className="tabular font-semibold">{retrain ? `${retrain.corrections_pending}/${retrain.threshold}` : "…"}</span>
          </a>
        )}
      </div>
      <ServerStatus state={backend.state} elapsed={backend.elapsed} retry={backend.retry} />

      <div className="mt-4 grid gap-4 lg:grid-cols-[280px_1fr] xl:grid-cols-[240px_minmax(250px,290px)_1fr]">
        {/* inbox */}
        <Card className="gap-3 py-4 lg:row-span-2 xl:row-span-1">
          <CardHeader className="px-4">
            <CardTitle className="flex items-center gap-2 text-base">
              <Inbox className="size-4" /> Inbox
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 px-4">
            {samples.length === 0 && backend.state === "ready" && <p className="text-sm text-muted-foreground">Loading samples…</p>}
            {samples.map((s) => (
              <button
                key={s.id}
                disabled={running}
                onClick={() => run({ kind: "sample", id: s.id })}
                className={cn(
                  "w-full rounded-md border p-2.5 text-left transition-colors hover:bg-muted/60 disabled:opacity-60",
                  source?.kind === "sample" && source.id === s.id && "border-primary bg-primary/5",
                )}
              >
                <p className="text-sm font-medium">{s.title}</p>
                <p className="line-clamp-1 text-xs text-muted-foreground">{s.body.replace(/\s+/g, " ")}</p>
              </button>
            ))}
            <button
              onClick={() => setSource({ kind: "custom" })}
              className={cn(
                "flex w-full items-center gap-2 rounded-md border border-dashed p-2.5 text-left text-sm hover:bg-muted/60",
                source?.kind === "custom" && "border-primary",
              )}
            >
              <PenLine className="size-4" /> Paste your own email
            </button>
            {source?.kind === "custom" && (
              <div className="space-y-2 pt-1">
                <Input value={custom.sender} onChange={(e) => setCustom({ ...custom, sender: e.target.value })} placeholder="From" className="text-xs" />
                <Input value={custom.subject} onChange={(e) => setCustom({ ...custom, subject: e.target.value })} placeholder="Subject" className="text-xs" />
                <Textarea
                  value={custom.body}
                  onChange={(e) => setCustom({ ...custom, body: e.target.value })}
                  placeholder="hey need 6 45/5 caps and a contactor for my KVL-AC24-2 asap"
                  rows={7}
                  maxLength={6000}
                  className="text-xs"
                />
                <p className="text-[11px] text-muted-foreground">
                  Please don&apos;t paste real or personal data. Use a demo customer address (like the one above) to get their pricing.
                  {!isAdmin && " Public input is handled by the small model only; low-confidence results are flagged for review."}
                </p>
                <Button size="sm" className="w-full" disabled={running || !custom.body.trim()} onClick={() => run({ kind: "custom" }, custom)}>
                  {running ? <Loader2 className="size-4 animate-spin" /> : <Play className="size-4" />} Process
                </Button>
              </div>
            )}
          </CardContent>
        </Card>

        {/* timeline */}
        <Card className="gap-3 py-4">
          <CardHeader className="px-4">
            <CardTitle className="text-base">Pipeline</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 px-4">
            {selected && (
              <div className="rounded-md bg-muted/40 p-2.5 text-xs">
                <p className="font-medium">{selected.subject || "(no subject)"}</p>
                <p className="text-muted-foreground">{selected.sender}</p>
                <p className="mt-1.5 whitespace-pre-wrap">{selected.body}</p>
                <p className="mt-2 italic text-muted-foreground">{selected.demonstrates}</p>
              </div>
            )}
            {source ? <Timeline steps={steps} running={running} /> : <p className="text-sm text-muted-foreground">Choose an email to start.</p>}
          </CardContent>
        </Card>

        {/* quote */}
        <Card className="gap-3 py-4">
          <CardHeader className="px-4">
            <CardTitle className="text-base">Draft quote</CardTitle>
          </CardHeader>
          <CardContent className="px-4">
            {error && <p className="mb-3 rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">{error}</p>}
            {notice && (
              <p className="mb-3 flex items-center gap-2 rounded-md border border-emerald-500/40 bg-emerald-500/5 p-3 text-sm">
                <CheckCircle2 className="size-4 shrink-0 text-emerald-600" /> {notice}
              </p>
            )}
            {quote ? (
              <QuoteView
                key={`${quote.id}-${quoteVersion}`}
                quote={quote}
                isAdmin={isAdmin}
                emailText={source?.kind === "custom" ? custom.body : (selected?.body ?? "")}
                corrections={retrain ? { pending: retrain.corrections_pending, threshold: retrain.threshold } : null}
                onCorrected={onCorrected}
              />
            ) : running ? (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="size-4 animate-spin" /> Working on it…
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">The draft quote appears here.</p>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
