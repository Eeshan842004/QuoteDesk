"use client";

import { useState } from "react";
import { PencilLine, Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import { intentLabel } from "@/lib/format";
import type { CorrectionItemPayload, CorrectionPayload, CorrectionResult, Quote } from "@/lib/types";

const INTENTS = ["quote_request", "order_status", "return_request", "product_question", "other"] as const;
const UNITS = ["each", "box", "case", "roll", "pack", "ft", "tube", "pair"];
const NO_ITEMS = new Set(["order_status", "other"]);

const blankItem = (): CorrectionItemPayload => ({
  description: "", quantity: null, unit: null, part_number: null, compatible_with: null,
  reference: null, needs_size_or_spec: false, needs_equipment_model: false,
});

/** Start from what the model extracted, so the admin only edits what is wrong. */
function initial(quote: Quote): CorrectionPayload {
  const e = quote.extraction;
  const flagged = (kind: string, desc: string) =>
    (e?.missing_info ?? []).some((m) => m.startsWith(`${kind}:`) && m.slice(kind.length + 1).trim().toLowerCase() === desc.trim().toLowerCase());
  return {
    intent: (e?.intent && e.intent !== "unknown" ? e.intent : "quote_request") as CorrectionPayload["intent"],
    urgency: e?.urgency ?? "normal",
    needed_by: e?.needed_by ?? null,
    note: "",
    items: (e?.items ?? []).map((it) => ({
      description: it.description,
      quantity: it.quantity,
      unit: it.unit,
      part_number: it.part_number,
      compatible_with: it.compatible_with,
      reference: it.reference === "previous_order" ? "previous_order" : null,
      needs_size_or_spec: flagged("size_or_spec", it.description),
      needs_equipment_model: flagged("equipment_model", it.description),
    })),
  };
}

export function CorrectionEditor({
  quote,
  emailText,
  disabled,
  onSaved,
}: {
  quote: Quote;
  emailText: string;
  disabled?: boolean;
  onSaved: (r: CorrectionResult) => void;
}) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<CorrectionPayload>(() => initial(quote));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const noItems = NO_ITEMS.has(form.intent);

  const setItem = (i: number, patch: Partial<CorrectionItemPayload>) =>
    setForm((f) => ({ ...f, items: f.items.map((it, j) => (j === i ? { ...it, ...patch } : it)) }));

  async function save() {
    setBusy(true);
    setError(null);
    try {
      const payload: CorrectionPayload = {
        ...form,
        needed_by: form.needed_by?.trim() || null,
        items: noItems
          ? []
          : form.items
              .filter((it) => it.description.trim())
              .map((it) => ({
                ...it,
                description: it.description.trim(),
                part_number: it.part_number?.trim() || null,
                compatible_with: it.compatible_with?.trim() || null,
                unit: it.quantity ? it.unit : null,
              })),
      };
      const res = await api.correct(quote.id, payload);
      setOpen(false);
      onSaved(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (o) {
          setForm(initial(quote));
          setError(null);
        }
        setOpen(o);
      }}
    >
      <DialogTrigger asChild>
        <Button variant="outline" disabled={disabled}>
          <PencilLine className="size-4" /> Correct result
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[92vh] overflow-y-auto sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>Correct what the model read</DialogTitle>
          <DialogDescription>
            Fix the extraction, not the prices. Saving adds this email and your corrected result to the next training run.
            Text fields must be copied exactly from the email.
          </DialogDescription>
        </DialogHeader>

        <div className="rounded-md border bg-muted/40 p-3">
          <p className="mb-1 text-xs font-medium text-muted-foreground">Email</p>
          <pre className="max-h-40 overflow-auto text-xs whitespace-pre-wrap">{emailText}</pre>
        </div>

        <div className="grid gap-3 sm:grid-cols-3">
          <label className="space-y-1 text-xs font-medium">
            Intent
            <Select value={form.intent} onValueChange={(v) => setForm({ ...form, intent: v as CorrectionPayload["intent"] })}>
              <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
              <SelectContent>
                {INTENTS.map((i) => <SelectItem key={i} value={i}>{intentLabel[i]}</SelectItem>)}
              </SelectContent>
            </Select>
          </label>
          <label className="space-y-1 text-xs font-medium">
            Urgency
            <Select value={form.urgency} onValueChange={(v) => setForm({ ...form, urgency: v as CorrectionPayload["urgency"] })}>
              <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
              <SelectContent>
                {["low", "normal", "high"].map((u) => <SelectItem key={u} value={u}>{u}</SelectItem>)}
              </SelectContent>
            </Select>
          </label>
          <label className="space-y-1 text-xs font-medium">
            Needed by (as written)
            <Input value={form.needed_by ?? ""} placeholder="e.g. by Friday" onChange={(e) => setForm({ ...form, needed_by: e.target.value })} />
          </label>
        </div>

        {noItems ? (
          <p className="rounded-md border bg-muted/30 p-3 text-sm text-muted-foreground">
            {intentLabel[form.intent]} emails have no items. Any items below are dropped when saved.
          </p>
        ) : (
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <p className="text-sm font-medium">Items</p>
              <Button size="sm" variant="outline" onClick={() => setForm({ ...form, items: [...form.items, blankItem()] })}>
                <Plus className="size-4" /> Add item
              </Button>
            </div>
            {form.items.length === 0 && <p className="text-sm text-muted-foreground">No items. Add the ones the customer asked for.</p>}
            {form.items.map((it, i) => (
              <div key={i} className="space-y-2 rounded-md border p-3">
                <div className="flex gap-2">
                  <label className="flex-1 space-y-1 text-xs font-medium">
                    What the customer wrote for this part
                    <Input value={it.description} onChange={(e) => setItem(i, { description: e.target.value })} placeholder="e.g. 45/5 capacitors" />
                  </label>
                  <Button size="icon" variant="ghost" aria-label="Remove item" className="mt-5" onClick={() => setForm({ ...form, items: form.items.filter((_, j) => j !== i) })}>
                    <Trash2 className="size-4" />
                  </Button>
                </div>
                <div className="grid gap-2 sm:grid-cols-4">
                  <label className="space-y-1 text-xs font-medium">
                    Quantity
                    <Input type="number" min={1} value={it.quantity ?? ""} placeholder="not stated"
                      onChange={(e) => setItem(i, { quantity: e.target.value ? Number(e.target.value) : null })} />
                  </label>
                  <label className="space-y-1 text-xs font-medium">
                    Unit (if written)
                    <Select value={it.unit ?? "none"} onValueChange={(v) => setItem(i, { unit: v === "none" ? null : v })}>
                      <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="none">none</SelectItem>
                        {UNITS.map((u) => <SelectItem key={u} value={u}>{u}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </label>
                  <label className="space-y-1 text-xs font-medium">
                    Part number (if written)
                    <Input className="font-mono text-xs" value={it.part_number ?? ""} placeholder="e.g. NB-CAP-1765"
                      onChange={(e) => setItem(i, { part_number: e.target.value })} />
                  </label>
                  <label className="space-y-1 text-xs font-medium">
                    Equipment model (if written)
                    <Input className="font-mono text-xs" value={it.compatible_with ?? ""} placeholder="e.g. KVL-AC24-2"
                      onChange={(e) => setItem(i, { compatible_with: e.target.value })} />
                  </label>
                </div>
                <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs">
                  <label className="flex items-center gap-1.5">
                    <input type="checkbox" checked={it.reference === "previous_order"} onChange={(e) => setItem(i, { reference: e.target.checked ? "previous_order" : null })} />
                    &ldquo;same as last time&rdquo;
                  </label>
                  <label className="flex items-center gap-1.5">
                    <input type="checkbox" checked={it.needs_size_or_spec} onChange={(e) => setItem(i, { needs_size_or_spec: e.target.checked })} />
                    too vague to pick one part (size / spec missing)
                  </label>
                  <label className="flex items-center gap-1.5">
                    <input type="checkbox" checked={it.needs_equipment_model} onChange={(e) => setItem(i, { needs_equipment_model: e.target.checked })} />
                    equipment model missing
                  </label>
                </div>
              </div>
            ))}
            <p className="text-xs text-muted-foreground">
              &ldquo;Quantity missing&rdquo; and &ldquo;order number missing&rdquo; are added automatically from the rules, so labels stay consistent.
            </p>
          </div>
        )}

        <label className="space-y-1 text-xs font-medium">
          Note (optional)
          <Textarea rows={2} value={form.note ?? ""} onChange={(e) => setForm({ ...form, note: e.target.value })} placeholder="Why was the model wrong?" />
        </label>
        {error && <p className="rounded-md border border-destructive/40 bg-destructive/5 p-2 text-sm text-destructive">{error}</p>}
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
          <Button onClick={save} disabled={busy}>{busy ? "Saving…" : "Save correction"}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
