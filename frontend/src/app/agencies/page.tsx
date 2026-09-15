"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Plus } from "lucide-react";
import { agenciesApi } from "@/lib/api/resources";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter } from "@/components/ui/dialog";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { SampleDataBadge } from "@/components/domain/badges";
import { LoadingState, ErrorState, EmptyState } from "@/components/ui/states";
import type { Agency } from "@/types";

export default function AgenciesPage() {
  const [agencies, setAgencies] = useState<Agency[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const router = useRouter();

  function load() {
    setError(null);
    agenciesApi.list(q || undefined).then(setAgencies).catch((e) => setError(e.message));
  }
  useEffect(load, [q]); // eslint-disable-line react-hooks/exhaustive-deps

  if (error) return <ErrorState message={error} onRetry={load} />;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-foreground">Agencies</h1>
          <p className="text-sm text-muted-foreground">Federal, state, and municipal agencies Principal pursues.</p>
        </div>
        <NewAgencyDialog onCreated={load} />
      </div>
      <Input placeholder="Search agencies…" value={q} onChange={(e) => setQ(e.target.value)} className="max-w-xs" />

      {!agencies ? (
        <LoadingState />
      ) : agencies.length === 0 ? (
        <EmptyState title="No agencies yet" />
      ) : (
        <Card>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Agency</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Priority Tier</TableHead>
                <TableHead>Offices</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {agencies.map((a) => (
                <TableRow key={a.id} className="cursor-pointer" onClick={() => router.push(`/agencies/${a.id}`)}>
                  <TableCell className="font-medium text-foreground">
                    <div className="flex items-center gap-2">
                      {a.name} {a.is_sample_data && <SampleDataBadge />}
                    </div>
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">{a.agency_type ?? "—"}</TableCell>
                  <TableCell><Badge variant={a.priority_tier === 1 ? "accent" : "muted"}>Tier {a.priority_tier}</Badge></TableCell>
                  <TableCell className="text-xs text-muted-foreground">{a.offices.length}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      )}
    </div>
  );
}

function NewAgencyDialog({ onCreated }: { onCreated: () => void }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [shortName, setShortName] = useState("");
  const [priorityTier, setPriorityTier] = useState("2");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setBusy(true);
    try {
      await agenciesApi.create({ name, short_name: shortName || null, priority_tier: Number(priorityTier) });
      setOpen(false);
      setName("");
      setShortName("");
      onCreated();
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild><Button size="sm"><Plus className="h-4 w-4" /> New Agency</Button></DialogTrigger>
      <DialogContent>
        <DialogHeader><DialogTitle>New Agency</DialogTitle></DialogHeader>
        <form onSubmit={submit} className="flex flex-col gap-3">
          <div><Label className="mb-1 block">Name</Label><Input value={name} onChange={(e) => setName(e.target.value)} required /></div>
          <div><Label className="mb-1 block">Short Name</Label><Input value={shortName} onChange={(e) => setShortName(e.target.value)} /></div>
          <div>
            <Label className="mb-1 block">Priority Tier (1 = highest)</Label>
            <Input type="number" min={1} max={3} value={priorityTier} onChange={(e) => setPriorityTier(e.target.value)} />
          </div>
          <DialogFooter><Button type="submit" disabled={busy}>Create</Button></DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
