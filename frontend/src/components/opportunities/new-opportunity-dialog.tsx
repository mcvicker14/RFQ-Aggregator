"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Plus } from "lucide-react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogTrigger } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { OpportunityForm } from "./opportunity-form";
import { opportunitiesApi } from "@/lib/api/resources";

export function NewOpportunityDialog() {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const router = useRouter();

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm"><Plus className="h-4 w-4" /> New Opportunity</Button>
      </DialogTrigger>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>New Opportunity</DialogTitle>
          <DialogDescription>
            Add an opportunity manually. It enters the pipeline at &quot;Signal Detected&quot; and is scored automatically.
          </DialogDescription>
        </DialogHeader>
        <OpportunityForm
          submitLabel="Create Opportunity"
          busy={busy}
          onSubmit={async (payload) => {
            setBusy(true);
            try {
              const created = await opportunitiesApi.create(payload);
              setOpen(false);
              router.push(`/opportunities/${created.id}`);
            } finally {
              setBusy(false);
            }
          }}
        />
      </DialogContent>
    </Dialog>
  );
}
