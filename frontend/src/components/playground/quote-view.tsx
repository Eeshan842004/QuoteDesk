"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { AlertTriangle, Check, ExternalLink, Plus, RotateCcw, ShieldAlert, Trash2, X } from "lucide-react";
import { LineStatusChip, PathBadge } from "@/components/bits";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api";
import { intentLabel, money, pct } from "@/lib/format";
import type { CorrectionResult, DecisionResult, LineDecision, Quote } from "@/lib/types";
import { CorrectionEditor } from "./correction-editor";
import { cn } from "@/lib/utils";

type Edit = { sku?: string; quantity?: number; removed?: boolean; reason?: LineDecision["reason"] };
type Added = { sku: string; quantity: number; description: string };

const REASONS: { value: NonNullable<LineDecision["reason"]>; label: string }[] = [
  { value: "misread", label: "Model misread the email" },
  { value: "wrong_part", label: "Wrong part picked" },
  { value: "business", label: "Business choice" },
];

export function QuoteView({
  quote,
  isAdmin,
  emailText,
  corrections,
  onCorrected,
}: {
  quote: Quote;
  isAdmin: boolean;
  emailText: string;
  corrections: { pending: number; threshold: number } | null;
  onCorrected: (r: CorrectionResult) => void;
}) {
  const [edits, setEdits] = useState<Record<number, Edit>>({});
  const [added, setAdded] = useState<Added[]>([]);
  const [newSku, setNewSku] = useState("");
  const [newQty, setNewQty] = useState(1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<DecisionResult | null>(null);
  const q = result?.quote ?? quote;
  const decided = !!q.decided_at;
  const f = q.flags || {};

  const decisions = useMemo<LineDecision[]>(() => {
    const out: LineDecision[] = [];
    for (const l of quote.lines) {
      const e = edits[l.line_no];
      if (!e) continue;
      if (e.removed) out.push({ line_no: l.line_no, action: "remove", reason: e.reason ?? "misread" });
      else {
        if (e.sku && e.sku !== l.sku) out.push({ line_no: l.line_no, action: "change_sku", sku: e.sku, reason: e.reason ?? "wrong_part" });
        if (e.quantity && e.quantity !== l.quantity) out.push({ line_no: l.line_no, action: "edit_quantity", quantity: e.quantity, reason: e.reason ?? "misread" });
      }
    }
    for (const a of added) out.push({ action: "add", sku: a.sku, quantity: a.quantity, description: a.description, reason: "misread" });
    return out;
  }, [edits, added, quote.lines]);

  async function decide(decision: "approve" | "reject") {
    setBusy(true);
    setError(null);
    try {
      setResult(await api.decide(quote.id, decision, decision === "approve" ? decisions : []));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const setEdit = (n: number, patch: Edit) => setEdits((s) => ({ ...s, [n]: { ...s[n], ...patch } }));

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="outline">{intentLabel[q.intent] ?? q.intent}</Badge>
        <PathBadge path={f.path} />
        {f.teacher_cached && <Badge variant="outline">cached expert result</Badge>}
        {f.admin_corrected && <Badge className="bg-emerald-600/10 text-emerald-700 dark:text-emerald-300">corrected by admin</Badge>}
        {f.confidence && f.confidence.validity > 0 && <Badge variant="outline">confidence {pct(f.confidence.score, 0)}</Badge>}
        {q.customer ? (
          <span className="text-sm text-muted-foreground">
            {q.customer.name} · tier {q.customer.tier}
          </span>
        ) : (
          <span className="text-sm text-muted-foreground">Unknown sender: list prices</span>
        )}
        <Link href={`/traces/${q.trace_id}`} className="ml-auto inline-flex items-center gap-1 text-sm text-primary hover:underline">
          View trace <ExternalLink className="size-3" />
        </Link>
      </div>

      {f.prompt_injection_suspected && (
        <div className="flex gap-2 rounded-md border border-red-400/40 bg-red-500/5 p-3 text-sm">
          <ShieldAlert className="mt-0.5 size-4 shrink-0 text-red-600" />
          <div>
            <p className="font-medium">prompt_injection_suspected</p>
            <p className="text-muted-foreground">
              The email contains instruction-like text ({(f.injection_matches ?? []).map((m) => `"${m.text}"`).join(", ")}). It was
              treated as data. Prices come only from the pricing tool, so the requested discount was not applied.
            </p>
          </div>
        </div>
      )}
      {!!f.needs_review_reasons?.length && (
        <div className="flex gap-2 rounded-md border border-amber-400/40 bg-amber-500/5 p-3 text-sm">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-500" />
          <ul className="list-inside list-disc text-muted-foreground">
            {f.needs_review_reasons.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        </div>
      )}

      {q.status === "no_quote" ? (
        <div className="rounded-lg border bg-muted/30 p-4">
          <p className="text-sm font-medium">No quote needed: suggested action</p>
          <p className="mt-1 text-sm text-muted-foreground">{q.suggested_action}</p>
        </div>
      ) : (
        <>
          <div className="overflow-x-auto rounded-lg border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="min-w-36">Customer wrote</TableHead>
                  <TableHead className="min-w-44">Catalog item</TableHead>
                  <TableHead className="w-20 text-right">Qty</TableHead>
                  <TableHead className="text-right">Total</TableHead>
                  <TableHead>Status</TableHead>
                  {!decided && <TableHead />}
                </TableRow>
              </TableHeader>
              <TableBody>
                {q.lines.map((l) => {
                  const e = edits[l.line_no] ?? {};
                  const changed = !!(e.removed || (e.sku && e.sku !== l.sku) || (e.quantity && e.quantity !== l.quantity));
                  return (
                    <TableRow key={l.line_no} className={cn((e.removed || l.removed) && "opacity-40 line-through")}>
                      <TableCell className="max-w-44 align-top text-sm whitespace-normal">
                        <p>{l.description}</p>
                        {l.reason && <p className="mt-1 text-xs text-amber-700 dark:text-amber-400">{l.reason}</p>}
                        {changed && !decided && (
                          <Select value={e.reason ?? (e.sku ? "wrong_part" : "misread")} onValueChange={(v) => setEdit(l.line_no, { reason: v as Edit["reason"] })}>
                            <SelectTrigger size="sm" className="mt-2 h-7 text-xs">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              {REASONS.map((r) => (
                                <SelectItem key={r.value} value={r.value} className="text-xs">
                                  {r.label}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        )}
                      </TableCell>
                      <TableCell className="align-top text-sm">
                        {!decided && l.candidates.length > 1 ? (
                          <Select value={e.sku ?? l.sku ?? undefined} onValueChange={(v) => setEdit(l.line_no, { sku: v })}>
                            <SelectTrigger className="h-auto min-h-9 w-full min-w-40 text-left text-xs whitespace-normal">
                              <SelectValue placeholder="choose a part" />
                            </SelectTrigger>
                            <SelectContent>
                              {l.candidates.map((c) => (
                                <SelectItem key={c.sku} value={c.sku} className="text-xs">
                                  <span className="font-mono">{c.sku}</span> · {c.name} · {pct(c.score, 0)}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        ) : l.sku ? (
                          <div>
                            <p className="font-mono text-xs">{l.sku}</p>
                            <p className="text-xs text-muted-foreground">{l.name}</p>
                          </div>
                        ) : (
                          <span className="text-xs text-muted-foreground">no match</span>
                        )}
                        {l.stock_qty != null && <p className="mt-1 text-xs text-muted-foreground">{l.stock_qty} in stock</p>}
                      </TableCell>
                      <TableCell className="text-right align-top">
                        {decided ? (
                          <span className="tabular">{l.quantity ?? "–"}</span>
                        ) : (
                          <Input
                            type="number"
                            min={1}
                            className="h-8 w-20 text-right"
                            value={e.quantity ?? l.quantity ?? ""}
                            placeholder="?"
                            onChange={(ev) => setEdit(l.line_no, { quantity: Number(ev.target.value) || undefined })}
                          />
                        )}
                      </TableCell>
                      <TableCell className="tabular text-right align-top text-sm whitespace-nowrap">
                        {changed && !decided ? (
                          <span className="text-xs text-muted-foreground">repriced on approval</span>
                        ) : (
                          <>
                            {money(l.line_total)}
                            {l.unit_price != null && (
                              <p className="text-xs text-muted-foreground">
                                {money(l.unit_price)} ea{l.discount_pct ? ` (−${pct(l.discount_pct, 0)})` : ""}
                              </p>
                            )}
                          </>
                        )}
                      </TableCell>
                      <TableCell className="align-top">
                        {l.added_by_user ? <Badge variant="outline">added</Badge> : <LineStatusChip status={l.status} />}
                      </TableCell>
                      {!decided && (
                        <TableCell className="align-top">
                          <Button
                            size="icon"
                            variant="ghost"
                            aria-label={e.removed ? "Restore line" : "Remove line"}
                            onClick={() => setEdit(l.line_no, { removed: !e.removed })}
                          >
                            {e.removed ? <RotateCcw className="size-4" /> : <Trash2 className="size-4" />}
                          </Button>
                        </TableCell>
                      )}
                    </TableRow>
                  );
                })}
                {added.map((a, i) => (
                  <TableRow key={`add-${i}`} className="bg-primary/5">
                    <TableCell className="text-sm">{a.description}</TableCell>
                    <TableCell className="font-mono text-xs">{a.sku}</TableCell>
                    <TableCell className="tabular text-right">{a.quantity}</TableCell>
                    <TableCell className="text-right text-xs text-muted-foreground">
                      priced on approval
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline">new</Badge>
                    </TableCell>
                    <TableCell>
                      <Button size="icon" variant="ghost" onClick={() => setAdded(added.filter((_, j) => j !== i))} aria-label="Remove added line">
                        <X className="size-4" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>

          {!decided && (
            <div className="flex flex-wrap items-end gap-2">
              <div>
                <p className="mb-1 text-xs text-muted-foreground">Add a line the model missed</p>
                <Input className="h-8 w-40 font-mono text-xs" placeholder="NB-XXX-0000" value={newSku} onChange={(e) => setNewSku(e.target.value.toUpperCase())} />
              </div>
              <Input type="number" min={1} className="h-8 w-20" value={newQty} onChange={(e) => setNewQty(Number(e.target.value) || 1)} />
              <Button
                size="sm"
                variant="outline"
                disabled={!/^NB-[A-Z]{3}-\d{4}$/.test(newSku)}
                onClick={() => {
                  setAdded([...added, { sku: newSku, quantity: newQty, description: `added: ${newSku}` }]);
                  setNewSku("");
                  setNewQty(1);
                }}
              >
                <Plus className="size-4" /> Add
              </Button>
              <p className="tabular ml-auto text-sm">
                Draft total <span className="font-semibold">{money(q.total)}</span>
              </p>
            </div>
          )}
        </>
      )}

      {error && <p className="text-sm text-destructive">{error}</p>}

      {!decided ? (
        <div className="flex flex-wrap items-center gap-2 border-t pt-4">
          <Button onClick={() => decide("approve")} disabled={busy}>
            <Check className="size-4" /> {decisions.length ? `Approve with ${decisions.length} change${decisions.length > 1 ? "s" : ""}` : "Approve"}
          </Button>
          <Button variant="outline" onClick={() => decide("reject")} disabled={busy}>
            <X className="size-4" /> Reject
          </Button>
          {isAdmin && <CorrectionEditor quote={q} emailText={emailText} disabled={busy} onSaved={onCorrected} />}
          {isAdmin && corrections && (
            <Link href="/models" className="tabular text-sm text-primary hover:underline">
              Corrections {corrections.pending}/{corrections.threshold}
            </Link>
          )}
          <p className="w-full text-xs text-muted-foreground">
            {isAdmin
              ? "Reject only discards this draft: it is not saved as a correction. To teach the model, use Correct result."
              : "Sandbox: your decisions are recorded but never used for training. Sign in as admin (key icon) to correct results for retraining."}
          </p>
        </div>
      ) : (
        <DecisionSummary quote={q} result={result} />
      )}
    </div>
  );
}

function DecisionSummary({ quote, result }: { quote: Quote; result: DecisionResult | null }) {
  return (
    <div className="space-y-2 rounded-lg border bg-muted/30 p-4 text-sm">
      <p className="font-medium">
        {quote.status === "rejected" ? "Rejected." : `Approved${quote.flags?.decision === "edited" ? " with edits" : ""} and marked as sent (simulated, no email leaves the demo).`}
      </p>
      {result && result.corrections.length > 0 && (
        <ul className="space-y-1">
          {result.corrections.map((c, i) => (
            <li key={i} className="flex flex-wrap items-center gap-2">
              <Badge variant="outline">{c.kind}</Badge>
              <span className="text-muted-foreground">{c.field.replace("_", " ")}</span>
              <span className="text-xs">
                {c.counts_for_training ? "→ becomes a training example" : c.kind === "RESOLUTION" ? "→ tool feedback (alias suggestion)" : "→ not training data"}
              </span>
            </li>
          ))}
        </ul>
      )}
      {result?.sandbox && <p className="text-xs text-muted-foreground">Sandbox decision: nothing here reaches the training set.</p>}
      {result?.retrain && (
        <p className="text-xs text-muted-foreground">
          Retraining progress: {result.retrain.corrections_pending} / {result.retrain.threshold} corrections.
        </p>
      )}
    </div>
  );
}
