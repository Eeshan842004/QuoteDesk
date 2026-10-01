"use client";

import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, Download, RotateCcw, Upload, XCircle } from "lucide-react";
import { AdminTokenDialog } from "@/components/admin-token-dialog";
import { Stat } from "@/components/bits";
import { ServerStatus } from "@/components/server-status";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { getAdminToken } from "@/lib/admin";
import { api } from "@/lib/api";
import { pct, timeAgo } from "@/lib/format";
import type { ModelVersion, ModelsResponse, RetrainRun } from "@/lib/types";
import { useBackend } from "@/lib/use-backend";

const STATUS_STYLE: Record<string, string> = {
  live: "bg-emerald-600/10 text-emerald-700 dark:text-emerald-300",
  rejected: "bg-red-500/10 text-red-700 dark:text-red-300",
  retired: "bg-muted text-muted-foreground",
  candidate: "bg-primary/10 text-primary",
};

export default function ModelsPage() {
  const backend = useBackend();
  const [data, setData] = useState<ModelsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [admin, setAdmin] = useState(false);

  const load = useCallback(() => api.models().then(setData).catch((e) => setError(String(e))), []);
  useEffect(() => {
    if (backend.state === "ready") load();
  }, [backend.state, load]);
  useEffect(() => {
    const sync = () => setAdmin(!!getAdminToken());
    sync();
    window.addEventListener("quotedesk-admin", sync);
    return () => window.removeEventListener("quotedesk-admin", sync);
  }, []);
  useEffect(() => {
    if (!data?.retrain.active_run) return;
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, [data?.retrain.active_run, load]);

  async function act(fn: () => Promise<unknown>, ok: string) {
    setMsg(null);
    setError(null);
    try {
      await fn();
      setMsg(ok);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  const r = data?.retrain;
  return (
    <div className="mx-auto max-w-6xl space-y-6 px-4 py-8">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Models</h1>
          <p className="text-sm text-muted-foreground">
            Admin corrections become training data. A retrained model is promoted only if it beats the live one on the sealed exam.
          </p>
        </div>
        {!admin && <AdminTokenDialog trigger={<Button variant="outline" size="sm">Admin sign-in</Button>} />}
      </div>
      <ServerStatus state={backend.state} elapsed={backend.elapsed} retry={backend.retry} />
      {error && <p className="rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">{error}</p>}
      {msg && <p className="rounded-md border bg-muted/40 p-3 text-sm">{msg}</p>}

      {data && r && (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Stat label="Live version" value={data.live.version ?? "–"} hint={data.live.state === "ready" ? `loaded in ${data.live.load_seconds ?? "?"}s` : data.live.state} />
            <Stat label="Retrain state" value={r.state.replace("_", " ").toLowerCase()} hint={r.auto_enabled ? "automatic mode" : "manual mode"} />
            <Stat label="Corrections" value={`${r.corrections_pending} / ${r.threshold}`} hint="admin extraction fixes since last run" />
            <Stat label="Versions" value={data.versions.length} />
          </div>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Retraining</CardTitle>
              <CardDescription>
                When {r.threshold} admin corrections accumulate, a run bundles base training data + corrections (exam overlap is checked),
                trains on Kaggle, and sends the new adapter through the safety gate.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <Progress value={Math.min(100, (100 * r.corrections_pending) / Math.max(1, r.threshold))} />
                <p className="mt-1 text-xs text-muted-foreground">
                  {r.corrections_pending} of {r.threshold} corrections collected
                </p>
              </div>
              {admin && (
                <div className="flex flex-wrap items-center gap-4">
                  <label className="flex items-center gap-2 text-sm">
                    <Switch
                      checked={!r.paused}
                      onCheckedChange={(on) => act(() => api.retrain(on ? "resume" : "pause"), on ? "Auto-retrain resumed." : "Auto-retrain paused.")}
                    />
                    Auto-retrain {r.paused ? "paused" : "active"}
                  </label>
                  <Button size="sm" variant="outline" disabled={!!r.active_run || r.corrections_pending === 0} onClick={() => act(() => api.retrain("trigger"), "Retrain run started.")}>
                    Retrain now
                  </Button>
                </div>
              )}
              <RunList runs={r.runs} admin={admin} />
              {admin && <RegisterForm onDone={(m) => act(async () => m, m)} onError={setError} />}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Version history</CardTitle>
              <CardDescription>Promotion gate: exam item F1 ≥ live + margin, JSON validity ≥ live, no intent class drops more than 2 points.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {data.versions.length === 0 && <p className="text-sm text-muted-foreground">No versions registered yet.</p>}
              {data.versions.map((v) => (
                <VersionRow key={v.version} v={v} admin={admin} onRollback={() => act(() => api.rollback(v.version), `Rolled back to ${v.version}.`)} />
              ))}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}

function VersionRow({ v, admin, onRollback }: { v: ModelVersion; admin: boolean; onRollback: () => void }) {
  const m = v.metrics as Record<string, number> | null;
  return (
    <div className="rounded-lg border p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-sm font-semibold">{v.version}</span>
        <Badge className={STATUS_STYLE[v.status]}>{v.status}</Badge>
        <span className="text-xs text-muted-foreground">
          {v.source} · {timeAgo(v.promoted_at ?? v.created_at)}
        </span>
        {m && (
          <span className="tabular ml-auto text-xs text-muted-foreground">
            item F1 {pct(m.item_f1)} · valid JSON {pct(m.json_validity_rate)} · intent {pct(m.intent_accuracy)}
          </span>
        )}
        {admin && v.status !== "live" && v.status !== "rejected" && (
          <Button size="sm" variant="ghost" onClick={onRollback}>
            <RotateCcw className="size-4" /> Roll back to this
          </Button>
        )}
      </div>
      {v.gate && (
        <ul className="mt-2 space-y-0.5 text-xs">
          {v.gate.checks.map((c) => (
            <li key={c.name} className="flex items-start gap-1.5">
              {c.ok ? <CheckCircle2 className="mt-0.5 size-3.5 text-emerald-600" /> : <XCircle className="mt-0.5 size-3.5 text-destructive" />}
              <span className={c.ok ? "text-muted-foreground" : ""}>{c.detail}</span>
            </li>
          ))}
        </ul>
      )}
      {v.notes && <p className="mt-1 text-xs text-muted-foreground">{v.notes}</p>}
    </div>
  );
}

function RunList({ runs, admin }: { runs: RetrainRun[]; admin: boolean }) {
  if (!runs.length) return <p className="text-sm text-muted-foreground">No retrain runs yet.</p>;
  return (
    <div className="space-y-2">
      {runs.map((run) => (
        <details key={run.id} className="rounded-md border">
          <summary className="flex cursor-pointer list-none flex-wrap items-center gap-2 px-3 py-2 text-sm">
            <span className="font-medium">Run #{run.id}</span>
            <Badge variant="outline">{run.state}</Badge>
            <span className="text-xs text-muted-foreground">
              {run.mode} · {run.candidate_version} · {run.corrections_count} corrections · {timeAgo(run.created_at)}
            </span>
            {run.reason && <span className="w-full text-xs text-destructive">{run.reason}</span>}
          </summary>
          <div className="space-y-2 border-t p-3 text-xs">
            {admin && run.bundle_available && (
              <Button size="sm" variant="outline" onClick={() => api.downloadBundle(run.id)}>
                <Download className="size-4" /> Download training bundle
              </Button>
            )}
            <ol className="space-y-1">
              {run.log.map((l, i) => (
                <li key={i} className="flex gap-2">
                  <span className="tabular shrink-0 text-muted-foreground">{l.ts.slice(11, 19)}</span>
                  <span>{l.msg}</span>
                </li>
              ))}
            </ol>
          </div>
        </details>
      ))}
    </div>
  );
}

function RegisterForm({ onDone, onError }: { onDone: (msg: string) => void; onError: (m: string) => void }) {
  const [version, setVersion] = useState("v2");
  const [revision, setRevision] = useState("");
  const [report, setReport] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit() {
    setBusy(true);
    try {
      const res = await api.register({ version, revision: revision || version, eval_report: JSON.parse(report) });
      onDone(res.promoted ? `${version} PROMOTED and now live.` : `${version} REJECTED by the gate: ${res.gate?.reasons.join("; ")}`);
    } catch (e) {
      onError(e instanceof SyntaxError ? "eval.json is not valid JSON" : e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <details className="rounded-md border">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 text-sm font-medium">
        <Upload className="size-4" /> Register a manually trained version
      </summary>
      <div className="space-y-2 border-t p-3">
        <p className="text-xs text-muted-foreground">
          After running the notebook on Kaggle with the downloaded bundle, paste its <code>eval.json</code>. The same safety gate decides.
        </p>
        <div className="flex gap-2">
          <Input className="w-24" value={version} onChange={(e) => setVersion(e.target.value)} placeholder="v2" />
          <Input value={revision} onChange={(e) => setRevision(e.target.value)} placeholder="HF tag (defaults to version)" />
        </div>
        <Textarea rows={5} value={report} onChange={(e) => setReport(e.target.value)} placeholder='{"system":"tuned","splits":{"exam":{...}}}' className="font-mono text-xs" />
        <Button size="sm" disabled={busy || !report || !/^v\d+$/.test(version)} onClick={submit}>
          Register & run gate
        </Button>
      </div>
    </details>
  );
}
