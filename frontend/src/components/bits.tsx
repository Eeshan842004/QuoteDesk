"use client";

import { useState } from "react";
import { AlertTriangle, CheckCircle2, ChevronDown, ChevronRight, CircleDashed, Loader2, MinusCircle, XCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

export function LineStatusChip({ status }: { status: "CONFIDENT" | "NEEDS_REVIEW" }) {
  return status === "CONFIDENT" ? (
    <Badge className="bg-emerald-600/10 text-emerald-700 dark:text-emerald-300">Confident</Badge>
  ) : (
    <Badge className="bg-amber-500/15 text-amber-800 dark:text-amber-300">Review</Badge>
  );
}

export function StepIcon({ status }: { status: string }) {
  switch (status) {
    case "running":
      return <Loader2 className="size-4 animate-spin text-primary" />;
    case "ok":
      return <CheckCircle2 className="size-4 text-emerald-600" />;
    case "flagged":
      return <AlertTriangle className="size-4 text-amber-500" />;
    case "error":
      return <XCircle className="size-4 text-destructive" />;
    case "skipped":
      return <MinusCircle className="size-4 text-muted-foreground" />;
    default:
      return <CircleDashed className="size-4 text-muted-foreground" />;
  }
}

export function PathBadge({ path }: { path?: string | null }) {
  if (!path) return null;
  const map: Record<string, string> = {
    student: "bg-primary/10 text-primary",
    teacher: "bg-violet-500/15 text-violet-700 dark:text-violet-300",
    teacher_cached: "bg-violet-500/15 text-violet-700 dark:text-violet-300",
    student_flagged: "bg-amber-500/15 text-amber-800 dark:text-amber-300",
    none: "bg-muted text-muted-foreground",
  };
  const label: Record<string, string> = {
    student: "small model",
    teacher: "expert model",
    teacher_cached: "expert model · cached",
    student_flagged: "small model · flagged",
    none: "manual",
  };
  return <Badge className={map[path] ?? "bg-muted"}>{label[path] ?? path}</Badge>;
}

export function JsonView({ value, label, defaultOpen = false }: { value: unknown; label: string; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  if (value == null) return null;
  return (
    <div className="rounded-md border">
      <button className="flex w-full items-center gap-1 px-2 py-1.5 text-left text-xs font-medium" onClick={() => setOpen(!open)}>
        {open ? <ChevronDown className="size-3" /> : <ChevronRight className="size-3" />}
        {label}
      </button>
      {open && (
        <pre className="max-h-96 overflow-auto border-t bg-muted/40 p-2 text-[11px] leading-relaxed whitespace-pre-wrap break-all">
          {typeof value === "string" ? value : JSON.stringify(value, null, 2)}
        </pre>
      )}
    </div>
  );
}

export function Stat({ label, value, hint, className }: { label: string; value: React.ReactNode; hint?: string; className?: string }) {
  return (
    <div className={cn("rounded-lg border p-3", className)}>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="tabular mt-1 text-xl font-semibold">{value}</p>
      {hint && <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}
