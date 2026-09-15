"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Plus } from "lucide-react";
import { contactsApi } from "@/lib/api/resources";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { LoadingState, ErrorState, EmptyState } from "@/components/ui/states";
import { formatDate, titleCase } from "@/lib/utils";
import type { Contact } from "@/types";

const ROLES = [
  "contracting_officer", "program_manager", "small_business_specialist", "technical_contact",
  "agency_engineer", "teaming_partner_contact", "municipal_official", "other",
];

export default function ContactsPage() {
  const [contacts, setContacts] = useState<Contact[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const router = useRouter();

  function load() {
    setError(null);
    contactsApi.list(q || undefined).then(setContacts).catch((e) => setError(e.message));
  }
  useEffect(load, [q]); // eslint-disable-line react-hooks/exhaustive-deps

  if (error) return <ErrorState message={error} onRetry={load} />;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-foreground">Contacts</h1>
          <p className="text-sm text-muted-foreground">Contracting officers, program managers, and partner contacts.</p>
        </div>
        <NewContactDialog onCreated={load} />
      </div>
      <Input placeholder="Search contacts…" value={q} onChange={(e) => setQ(e.target.value)} className="max-w-xs" />

      {!contacts ? (
        <LoadingState />
      ) : contacts.length === 0 ? (
        <EmptyState title="No contacts yet" />
      ) : (
        <Card>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Organization</TableHead>
                <TableHead>Role</TableHead>
                <TableHead>Email</TableHead>
                <TableHead>Next Follow-up</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {contacts.map((c) => (
                <TableRow key={c.id} className="cursor-pointer" onClick={() => router.push(`/contacts/${c.id}`)}>
                  <TableCell className="font-medium text-foreground">{c.full_name}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">{c.organization ?? "—"}</TableCell>
                  <TableCell><Badge variant="outline">{titleCase(c.role)}</Badge></TableCell>
                  <TableCell className="text-xs text-muted-foreground">{c.email ?? "—"}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">{formatDate(c.next_follow_up_date)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      )}
    </div>
  );
}

function NewContactDialog({ onCreated }: { onCreated: () => void }) {
  const [open, setOpen] = useState(false);
  const [fullName, setFullName] = useState("");
  const [organization, setOrganization] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("other");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!fullName.trim()) return;
    setBusy(true);
    try {
      await contactsApi.create({ full_name: fullName, organization: organization || null, email: email || null, role });
      setOpen(false);
      setFullName("");
      setOrganization("");
      setEmail("");
      onCreated();
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild><Button size="sm"><Plus className="h-4 w-4" /> New Contact</Button></DialogTrigger>
      <DialogContent>
        <DialogHeader><DialogTitle>New Contact</DialogTitle></DialogHeader>
        <form onSubmit={submit} className="flex flex-col gap-3">
          <div><Label className="mb-1 block">Full Name</Label><Input value={fullName} onChange={(e) => setFullName(e.target.value)} required /></div>
          <div><Label className="mb-1 block">Organization</Label><Input value={organization} onChange={(e) => setOrganization(e.target.value)} /></div>
          <div><Label className="mb-1 block">Email</Label><Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} /></div>
          <div>
            <Label className="mb-1 block">Role</Label>
            <Select value={role} onValueChange={setRole}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>{ROLES.map((r) => <SelectItem key={r} value={r}>{titleCase(r)}</SelectItem>)}</SelectContent>
            </Select>
          </div>
          <DialogFooter><Button type="submit" disabled={busy}>Create</Button></DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
