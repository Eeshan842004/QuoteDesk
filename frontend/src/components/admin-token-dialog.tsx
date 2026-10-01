"use client";

import { useEffect, useState } from "react";
import { KeyRound } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { getAdminToken, setAdminToken } from "@/lib/admin";

export function AdminTokenDialog({ trigger }: { trigger?: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState("");
  const [has, setHas] = useState(false);
  useEffect(() => {
    const sync = () => setHas(!!getAdminToken());
    sync();
    window.addEventListener("quotedesk-admin", sync);
    return () => window.removeEventListener("quotedesk-admin", sync);
  }, []);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        {trigger ?? (
          <Button variant="ghost" size="icon" aria-label="Admin token">
            <KeyRound className="size-4" />
          </Button>
        )}
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Admin token</DialogTitle>
          <DialogDescription>
            Visitors act in a sandbox: their decisions never become training data. With the admin token, corrections count
            toward retraining and model controls (pause, retrain, rollback) are enabled. The token is stored only in this browser.
          </DialogDescription>
        </DialogHeader>
        <Input type="password" placeholder="ADMIN_TOKEN" value={value} onChange={(e) => setValue(e.target.value)} />
        <DialogFooter className="gap-2">
          {has && (
            <Button
              variant="outline"
              onClick={() => {
                setAdminToken(null);
                setOpen(false);
              }}
            >
              Sign out
            </Button>
          )}
          <Button
            disabled={!value}
            onClick={() => {
              setAdminToken(value.trim());
              setValue("");
              setOpen(false);
            }}
          >
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
