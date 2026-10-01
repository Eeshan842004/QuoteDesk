"use client";

import { Loader2, RefreshCw, ServerCrash } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { BackendState } from "@/lib/use-backend";

export function ServerStatus({ state, elapsed, retry }: { state: BackendState; elapsed: number; retry: () => void }) {
  if (state === "ready") return null;
  if (state === "down")
    return (
      <div className="flex items-center gap-3 rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm">
        <ServerCrash className="size-5 text-destructive" />
        <div className="flex-1">
          <p className="font-medium">The demo server is not answering.</p>
          <p className="text-muted-foreground">It may have used up its free monthly compute. Please try again later.</p>
        </div>
        <Button variant="outline" size="sm" onClick={retry}>
          <RefreshCw className="size-4" /> Retry
        </Button>
      </div>
    );
  return (
    <div className="flex items-center gap-3 rounded-lg border bg-muted/40 p-4 text-sm">
      <Loader2 className="size-5 animate-spin text-primary" />
      <div>
        <p className="font-medium">{state === "checking" ? "Connecting to the server…" : "Waking up the server…"}</p>
        <p className="text-muted-foreground">
          The backend runs on free hosting that sleeps when idle. The first request loads the model, which usually takes
          30–90 seconds{elapsed > 3 ? ` (${elapsed}s so far)` : ""}. This page retries automatically.
        </p>
      </div>
    </div>
  );
}
