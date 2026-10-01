"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import type { Health } from "./types";

export type BackendState = "checking" | "waking" | "ready" | "down";

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** Polls /api/health until the (scale-to-zero) backend answers. Free hosting sleeps when idle. */
export function useBackend(maxWaitSec = 240) {
  const [state, setState] = useState<BackendState>("checking");
  const [health, setHealth] = useState<Health | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [round, setRound] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const started = Date.now();
    const tick = setInterval(() => setElapsed(Math.round((Date.now() - started) / 1000)), 1000);
    (async () => {
      for (let attempt = 1; !cancelled; attempt++) {
        try {
          const h = await api.health();
          if (cancelled) return;
          setHealth(h);
          setState("ready");
          return;
        } catch {
          if (cancelled) return;
          if ((Date.now() - started) / 1000 > maxWaitSec) {
            setState("down");
            return;
          }
          setState(attempt > 1 ? "waking" : "checking");
          await sleep(Math.min(5000, 1500 * attempt));
        }
      }
    })().finally(() => clearInterval(tick));
    return () => {
      cancelled = true;
      clearInterval(tick);
    };
  }, [maxWaitSec, round]);

  const retry = useCallback(() => {
    setState("checking");
    setElapsed(0);
    setRound((r) => r + 1);
  }, []);

  return { state, health, elapsed, retry };
}
