"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { FileText, Menu, ShieldCheck, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { getAdminToken } from "@/lib/admin";
import { ThemeToggle } from "./theme-toggle";
import { AdminTokenDialog } from "./admin-token-dialog";
import { Badge } from "@/components/ui/badge";

const NAV = [
  { href: "/playground", label: "Playground" },
  { href: "/results", label: "Results" },
  { href: "/models", label: "Models" },
  { href: "/traces", label: "Traces" },
  { href: "/how-it-works", label: "How it works" },
];

export function SiteHeader() {
  const path = usePathname();
  const [open, setOpen] = useState(false);
  const [admin, setAdmin] = useState(false);
  useEffect(() => {
    const sync = () => setAdmin(!!getAdminToken());
    sync();
    window.addEventListener("quotedesk-admin", sync);
    return () => window.removeEventListener("quotedesk-admin", sync);
  }, []);

  return (
    <header className="sticky top-0 z-40 border-b bg-background/85 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-7xl items-center gap-4 px-4">
        <Link href="/" className="flex items-center gap-2 font-semibold">
          <span className="grid size-7 place-items-center rounded-md bg-primary text-primary-foreground">
            <FileText className="size-4" />
          </span>
          QuoteDesk
        </Link>
        <nav className="hidden items-center gap-1 md:flex">
          {NAV.map((n) => (
            <Link
              key={n.href}
              href={n.href}
              className={cn(
                "rounded-md px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
                path?.startsWith(n.href) && "bg-muted text-foreground",
              )}
            >
              {n.label}
            </Link>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-1">
          {admin && (
            <Badge variant="outline" className="gap-1">
              <ShieldCheck className="size-3" /> admin
            </Badge>
          )}
          <AdminTokenDialog />
          <ThemeToggle />
          <button className="rounded-md p-2 md:hidden" onClick={() => setOpen(!open)} aria-label="Menu">
            {open ? <X className="size-4" /> : <Menu className="size-4" />}
          </button>
        </div>
      </div>
      {open && (
        <nav className="flex flex-col border-t px-4 py-2 md:hidden">
          {NAV.map((n) => (
            <Link key={n.href} href={n.href} onClick={() => setOpen(false)} className="py-2 text-sm">
              {n.label}
            </Link>
          ))}
        </nav>
      )}
    </header>
  );
}

export function DemoBanner() {
  return (
    <div className="border-b bg-amber-50 px-4 py-1.5 text-center text-xs text-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
      Demo with synthetic data and a fictional company (Northbeam Industrial Supply). No real emails are sent.
    </div>
  );
}
