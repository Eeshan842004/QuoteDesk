"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ShieldAlert } from "lucide-react";
import { PathBadge } from "@/components/bits";
import { ServerStatus } from "@/components/server-status";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api";
import { intentLabel, money, ms, timeAgo } from "@/lib/format";
import type { TraceRow } from "@/lib/types";
import { useBackend } from "@/lib/use-backend";

export default function TracesPage() {
  const backend = useBackend();
  const [rows, setRows] = useState<TraceRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (backend.state !== "ready") return;
    api.traces("?limit=100").then(setRows).catch((e) => setError(String(e)));
  }, [backend.state]);

  return (
    <div className="mx-auto max-w-6xl px-4 py-8">
      <h1 className="text-2xl font-semibold">Traces</h1>
      <p className="mb-4 text-sm text-muted-foreground">Every processed email keeps a full trace: each step, model call, tool call, token count and cost. This list shows the demo samples; emails you paste stay private and are reachable only from your own quote.</p>
      <ServerStatus state={backend.state} elapsed={backend.elapsed} retry={backend.retry} />
      {error && <p className="text-sm text-destructive">{error}</p>}
      {rows && rows.length === 0 && <p className="text-sm text-muted-foreground">No traces yet. Run an email in the Playground.</p>}
      {rows && rows.length > 0 && (
        <div className="overflow-x-auto rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Time</TableHead>
                <TableHead>Email</TableHead>
                <TableHead>Intent</TableHead>
                <TableHead>Path</TableHead>
                <TableHead className="text-right">Latency</TableHead>
                <TableHead className="text-right">Cost</TableHead>
                <TableHead>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((r) => (
                <TableRow key={r.id} className="cursor-pointer hover:bg-muted/50">
                  <TableCell className="text-xs whitespace-nowrap text-muted-foreground">{timeAgo(r.created_at)}</TableCell>
                  <TableCell className="max-w-72">
                    <Link href={`/traces/${r.id}`} className="block truncate text-sm font-medium hover:underline">
                      {r.subject || "(no subject)"}
                    </Link>
                    <p className="truncate text-xs text-muted-foreground">
                      {r.source === "sample" ? "sample · " : ""}
                      {r.sender}
                    </p>
                  </TableCell>
                  <TableCell className="text-sm">{r.intent ? intentLabel[r.intent] ?? r.intent : "–"}</TableCell>
                  <TableCell>
                    <div className="flex items-center gap-1">
                      <PathBadge path={r.path} />
                      {r.injection_suspected && <ShieldAlert className="size-4 text-red-500" aria-label="prompt injection suspected" />}
                    </div>
                  </TableCell>
                  <TableCell className="tabular text-right text-sm">{ms(r.latency_ms)}</TableCell>
                  <TableCell className="tabular text-right text-sm">{money(r.cost_usd, 4)}</TableCell>
                  <TableCell>
                    <Badge variant="outline">{r.status.replace("_", " ")}</Badge>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}
