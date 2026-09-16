"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Plus } from "lucide-react";
import { companiesApi } from "@/lib/api/resources";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { SampleDataBadge } from "@/components/domain/badges";
import { LoadingState, ErrorState, EmptyState } from "@/components/ui/states";
import { titleCase } from "@/lib/utils";
import type { Company } from "@/types";

const COMPANY_TYPES = ["own_firm", "teaming_partner", "competitor", "prime", "subconsultant", "other"];

function socioeconomicTags(c: Company): string[] {
  const tags: string[] = [];
  if (c.is_sdvosb) tags.push("SDVOSB");
  if (c.is_vosb) tags.push("VOSB");
  if (c.is_hubzone) tags.push("HUBZone");
  if (c.is_eight_a) tags.push("8(a)");
  if (c.is_wosb) tags.push("WOSB");
  if (c.is_edwosb) tags.push("EDWOSB");
  if (c.is_dbe) tags.push("DBE");
  if (c.is_small_business && tags.length === 0) tags.push("Small Business");
  return tags;
}

export default function CompaniesPage() {
  const [companies, setCompanies] = useState<Company[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [type, setType] = useState("all");
  const router = useRouter();

  function load() {
    setError(null);
    companiesApi
      .list({ q: q || undefined, company_type: type === "all" ? undefined : type })
      .then(setCompanies)
      .catch((e) => setError(e.message));
  }
  useEffect(load, [q, type]); // eslint-disable-line react-hooks/exhaustive-deps

  if (error) return <ErrorState message={error} onRetry={load} />;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-foreground">Companies</h1>
          <p className="text-sm text-muted-foreground">Teaming partners, competitors, and other firms Principal tracks.</p>
        </div>
        <NewCompanyDialog onCreated={load} />
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Input placeholder="Search companies…" value={q} onChange={(e) => setQ(e.target.value)} className="max-w-xs" />
        <Select value={type} onValueChange={setType}>
          <SelectTrigger className="w-48"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All types</SelectItem>
            {COMPANY_TYPES.map((t) => <SelectItem key={t} value={t}>{titleCase(t)}</SelectItem>)}
          </SelectContent>
        </Select>
      </div>

      {!companies ? (
        <LoadingState />
      ) : companies.length === 0 ? (
        <EmptyState title="No companies yet" />
      ) : (
        <Card>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Company</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Socioeconomic</TableHead>
                <TableHead>Location</TableHead>
                <TableHead>Specialties</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {companies.map((c) => (
                <TableRow key={c.id} className="cursor-pointer" onClick={() => router.push(`/companies/${c.id}`)}>
                  <TableCell className="font-medium text-foreground">
                    <div className="flex items-center gap-2">{c.name} {c.is_sample_data && <SampleDataBadge />}</div>
                  </TableCell>
                  <TableCell><Badge variant="outline">{titleCase(c.company_type)}</Badge></TableCell>
                  <TableCell>
                    <div className="flex flex-wrap gap-1">
                      {socioeconomicTags(c).map((t) => <Badge key={t} variant="secondary">{t}</Badge>)}
                    </div>
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {c.headquarters_city ? `${c.headquarters_city}, ${c.headquarters_state}` : "—"}
                  </TableCell>
                  <TableCell className="max-w-[240px] truncate text-xs text-muted-foreground">{c.technical_specialties ?? "—"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      )}
    </div>
  );
}

function NewCompanyDialog({ onCreated }: { onCreated: () => void }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [companyType, setCompanyType] = useState("teaming_partner");
  const [isSdvosb, setIsSdvosb] = useState(false);
  const [specialties, setSpecialties] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setBusy(true);
    try {
      await companiesApi.create({ name, company_type: companyType, is_sdvosb: isSdvosb, technical_specialties: specialties || null });
      setOpen(false);
      setName("");
      setSpecialties("");
      onCreated();
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild><Button size="sm"><Plus className="h-4 w-4" /> New Company</Button></DialogTrigger>
      <DialogContent>
        <DialogHeader><DialogTitle>New Company</DialogTitle></DialogHeader>
        <form onSubmit={submit} className="flex flex-col gap-3">
          <div><Label className="mb-1 block">Name</Label><Input value={name} onChange={(e) => setName(e.target.value)} required /></div>
          <div>
            <Label className="mb-1 block">Type</Label>
            <Select value={companyType} onValueChange={setCompanyType}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>{COMPANY_TYPES.map((t) => <SelectItem key={t} value={t}>{titleCase(t)}</SelectItem>)}</SelectContent>
            </Select>
          </div>
          <div><Label className="mb-1 block">Technical Specialties</Label><Input value={specialties} onChange={(e) => setSpecialties(e.target.value)} /></div>
          <label className="flex items-center gap-2 text-sm text-foreground">
            <input type="checkbox" checked={isSdvosb} onChange={(e) => setIsSdvosb(e.target.checked)} className="h-4 w-4 rounded border-input" />
            SDVOSB certified
          </label>
          <DialogFooter><Button type="submit" disabled={busy}>Create</Button></DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
