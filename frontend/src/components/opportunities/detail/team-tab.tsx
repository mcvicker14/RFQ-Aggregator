"use client";

import { useEffect, useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { companiesApi, contactsApi } from "@/lib/api/resources";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { EmptyState, LoadingState } from "@/components/ui/states";
import { titleCase } from "@/lib/utils";
import type { Company, Contact, OpportunityCompanyLink, OpportunityContactLink } from "@/types";

const RELATIONSHIPS = [
  "teaming_partner", "prime", "subconsultant", "incumbent",
  "confirmed_competitor", "historical_competitor", "likely_competitor", "possible_competitor",
];
const CONTACT_ROLES = [
  "contracting_officer", "program_manager", "small_business_specialist", "technical_contact",
  "agency_engineer", "teaming_partner_contact", "municipal_official", "other",
];

const COMPETITOR_RELS = new Set(["confirmed_competitor", "historical_competitor", "likely_competitor", "possible_competitor"]);

function relationshipVariant(rel: string) {
  if (rel === "teaming_partner") return "success" as const;
  if (COMPETITOR_RELS.has(rel)) return "destructive" as const;
  return "secondary" as const;
}

export function TeamTab({ opportunityId }: { opportunityId: string }) {
  const [links, setLinks] = useState<OpportunityCompanyLink[] | null>(null);
  const [contactLinks, setContactLinks] = useState<OpportunityContactLink[] | null>(null);

  function load() {
    companiesApi.listForOpportunity(opportunityId).then(setLinks).catch(() => setLinks([]));
    contactsApi.listForOpportunity(opportunityId).then(setContactLinks).catch(() => setContactLinks([]));
  }
  useEffect(load, [opportunityId]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle>Teaming Partners &amp; Competitors</CardTitle>
          <AddCompanyDialog opportunityId={opportunityId} onAdded={load} />
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          {!links ? (
            <LoadingState />
          ) : links.length === 0 ? (
            <EmptyState title="No companies linked yet" description="Add teaming partners or likely competitors." />
          ) : (
            links.map((link) => (
              <div key={link.id} className="flex items-start justify-between gap-3 border-b border-border pb-3 last:border-0 last:pb-0">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-foreground">{link.company.name}</span>
                    <Badge variant={relationshipVariant(link.relationship_type)}>{titleCase(link.relationship_type)}</Badge>
                  </div>
                  {link.rationale && <p className="mt-1 text-xs text-muted-foreground">{link.rationale}</p>}
                  <p className="mt-0.5 text-[11px] text-muted-foreground">Confidence: {titleCase(link.confidence)}</p>
                </div>
                <button
                  onClick={async () => { await companiesApi.unlink(link.id); load(); }}
                  className="text-muted-foreground hover:text-destructive"
                  aria-label="Remove"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            ))
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle>Contacts</CardTitle>
          <AddContactDialog opportunityId={opportunityId} onAdded={load} />
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          {!contactLinks ? (
            <LoadingState />
          ) : contactLinks.length === 0 ? (
            <EmptyState title="No contacts linked yet" description="Associate contracting officers, program managers, or partner contacts." />
          ) : (
            contactLinks.map((link) => (
              <div key={link.id} className="flex items-start justify-between gap-3 border-b border-border pb-3 last:border-0 last:pb-0">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-foreground">{link.contact.full_name}</span>
                    <Badge variant="outline">{titleCase(link.role_on_opportunity)}</Badge>
                  </div>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    {link.contact.organization} {link.contact.email ? `· ${link.contact.email}` : ""}
                  </p>
                </div>
                <button
                  onClick={async () => { await contactsApi.unlink(link.id); load(); }}
                  className="text-muted-foreground hover:text-destructive"
                  aria-label="Remove"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            ))
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function AddCompanyDialog({ opportunityId, onAdded }: { opportunityId: string; onAdded: () => void }) {
  const [open, setOpen] = useState(false);
  const [companies, setCompanies] = useState<Company[]>([]);
  const [companyId, setCompanyId] = useState("");
  const [relationship, setRelationship] = useState("teaming_partner");
  const [rationale, setRationale] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open) companiesApi.list().then(setCompanies).catch(() => setCompanies([]));
  }, [open]);

  async function submit() {
    if (!companyId) return;
    setBusy(true);
    try {
      await companiesApi.linkToOpportunity(opportunityId, { company_id: companyId, relationship_type: relationship, rationale: rationale || null });
      setOpen(false);
      setRationale("");
      onAdded();
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild><Button size="sm" variant="outline"><Plus className="h-3.5 w-3.5" /> Add</Button></DialogTrigger>
      <DialogContent>
        <DialogHeader><DialogTitle>Add Company to Opportunity</DialogTitle></DialogHeader>
        <div className="flex flex-col gap-3">
          <Select value={companyId} onValueChange={setCompanyId}>
            <SelectTrigger><SelectValue placeholder="Select company" /></SelectTrigger>
            <SelectContent>
              {companies.map((c) => <SelectItem key={c.id} value={c.id}>{c.name}</SelectItem>)}
            </SelectContent>
          </Select>
          <Select value={relationship} onValueChange={setRelationship}>
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              {RELATIONSHIPS.map((r) => <SelectItem key={r} value={r}>{titleCase(r)}</SelectItem>)}
            </SelectContent>
          </Select>
          <Textarea placeholder="Why is this company relevant? (recommended for competitors)" value={rationale} onChange={(e) => setRationale(e.target.value)} rows={2} />
        </div>
        <DialogFooter>
          <Button onClick={submit} disabled={busy || !companyId}>Add</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function AddContactDialog({ opportunityId, onAdded }: { opportunityId: string; onAdded: () => void }) {
  const [open, setOpen] = useState(false);
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [contactId, setContactId] = useState("");
  const [role, setRole] = useState("other");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open) contactsApi.list().then(setContacts).catch(() => setContacts([]));
  }, [open]);

  async function submit() {
    if (!contactId) return;
    setBusy(true);
    try {
      await contactsApi.linkToOpportunity(opportunityId, { contact_id: contactId, role_on_opportunity: role });
      setOpen(false);
      onAdded();
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild><Button size="sm" variant="outline"><Plus className="h-3.5 w-3.5" /> Add</Button></DialogTrigger>
      <DialogContent>
        <DialogHeader><DialogTitle>Add Contact to Opportunity</DialogTitle></DialogHeader>
        <div className="flex flex-col gap-3">
          <Select value={contactId} onValueChange={setContactId}>
            <SelectTrigger><SelectValue placeholder="Select contact" /></SelectTrigger>
            <SelectContent>
              {contacts.map((c) => <SelectItem key={c.id} value={c.id}>{c.full_name} — {c.organization}</SelectItem>)}
            </SelectContent>
          </Select>
          <Select value={role} onValueChange={setRole}>
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              {CONTACT_ROLES.map((r) => <SelectItem key={r} value={r}>{titleCase(r)}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
        <DialogFooter>
          <Button onClick={submit} disabled={busy || !contactId}>Add</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
