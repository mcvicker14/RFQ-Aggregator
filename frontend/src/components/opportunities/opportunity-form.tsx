"use client";

import { useEffect, useState } from "react";
import { agenciesApi, companiesApi } from "@/lib/api/resources";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { toDatetimeLocal } from "@/lib/utils";
import type { Agency, Company, Opportunity } from "@/types";

const SET_ASIDES = ["unrestricted", "sdvosb", "small_business", "eight_a", "hubzone", "wosb", "edwosb", "other"];
const CONTRACT_TYPES = ["ae_brooks_act", "idiq", "matoc", "satoc", "task_order", "design_build", "construction", "other"];
const MATURITY_STAGES = [
  "rumored_conceptual", "funding_identified", "planning", "procurement_forecast", "sources_sought_rfi",
  "solicitation_expected", "solicitation_released", "proposal_submitted", "interview_negotiation",
  "award_pending", "awarded",
];

export interface OpportunityFormValues {
  title: string;
  agency_id: string;
  solicitation_number: string;
  location_city: string;
  location_state: string;
  naics_code: string;
  psc_code: string;
  set_aside: string;
  contract_type: string;
  estimated_value_low: string;
  estimated_value_high: string;
  estimated_fee: string;
  contract_duration_months: string;
  proposal_due_at: string;
  questions_due_at: string;
  site_visit_at: string;
  industry_day_at: string;
  sources_sought_due_at: string;
  incumbent_company_id: string;
  incumbent_notes: string;
  description: string;
  scope_summary: string;
  evaluation_factors: string;
  past_performance_requirements: string;
  internal_notes: string;
  opportunity_source_label: string;
  maturity_stage: string;
}

function fromOpportunity(opp?: Partial<Opportunity>): OpportunityFormValues {
  return {
    title: opp?.title ?? "",
    agency_id: opp?.agency_id ?? "",
    solicitation_number: opp?.solicitation_number ?? "",
    location_city: opp?.location_city ?? "",
    location_state: opp?.location_state ?? "",
    naics_code: opp?.naics_code ?? "541330",
    psc_code: opp?.psc_code ?? "",
    set_aside: opp?.set_aside ?? "unrestricted",
    contract_type: opp?.contract_type ?? "other",
    estimated_value_low: opp?.estimated_value_low?.toString() ?? "",
    estimated_value_high: opp?.estimated_value_high?.toString() ?? "",
    estimated_fee: opp?.estimated_fee?.toString() ?? "",
    contract_duration_months: opp?.contract_duration_months?.toString() ?? "",
    proposal_due_at: toDatetimeLocal(opp?.proposal_due_at),
    questions_due_at: toDatetimeLocal(opp?.questions_due_at),
    site_visit_at: toDatetimeLocal(opp?.site_visit_at),
    industry_day_at: toDatetimeLocal(opp?.industry_day_at),
    sources_sought_due_at: toDatetimeLocal(opp?.sources_sought_due_at),
    incumbent_company_id: opp?.incumbent_company_id ?? "",
    incumbent_notes: opp?.incumbent_notes ?? "",
    description: opp?.description ?? "",
    scope_summary: opp?.scope_summary ?? "",
    evaluation_factors: opp?.evaluation_factors ?? "",
    past_performance_requirements: opp?.past_performance_requirements ?? "",
    internal_notes: opp?.internal_notes ?? "",
    opportunity_source_label: opp?.opportunity_source_label ?? "Manual Entry",
    maturity_stage: opp?.maturity_stage ?? "solicitation_released",
  };
}

function toPayload(values: OpportunityFormValues): Record<string, unknown> {
  const num = (v: string) => (v.trim() === "" ? null : Number(v));
  const str = (v: string) => (v.trim() === "" ? null : v);
  const dt = (v: string) => (v.trim() === "" ? null : new Date(v).toISOString());
  return {
    title: values.title,
    agency_id: str(values.agency_id),
    solicitation_number: str(values.solicitation_number),
    location_city: str(values.location_city),
    location_state: str(values.location_state)?.toUpperCase() ?? null,
    naics_code: str(values.naics_code),
    psc_code: str(values.psc_code),
    set_aside: values.set_aside,
    contract_type: values.contract_type,
    estimated_value_low: num(values.estimated_value_low),
    estimated_value_high: num(values.estimated_value_high),
    estimated_fee: num(values.estimated_fee),
    contract_duration_months: values.contract_duration_months.trim() === "" ? null : parseInt(values.contract_duration_months, 10),
    proposal_due_at: dt(values.proposal_due_at),
    questions_due_at: dt(values.questions_due_at),
    site_visit_at: dt(values.site_visit_at),
    industry_day_at: dt(values.industry_day_at),
    sources_sought_due_at: dt(values.sources_sought_due_at),
    incumbent_company_id: str(values.incumbent_company_id),
    incumbent_notes: str(values.incumbent_notes),
    description: str(values.description),
    scope_summary: str(values.scope_summary),
    evaluation_factors: str(values.evaluation_factors),
    past_performance_requirements: str(values.past_performance_requirements),
    internal_notes: str(values.internal_notes),
    opportunity_source_label: values.opportunity_source_label || "Manual Entry",
    maturity_stage: values.maturity_stage,
  };
}

export function OpportunityForm({
  initial,
  onSubmit,
  submitLabel = "Save",
  busy,
}: {
  initial?: Partial<Opportunity>;
  onSubmit: (payload: Record<string, unknown>) => Promise<void>;
  submitLabel?: string;
  busy?: boolean;
}) {
  const [values, setValues] = useState<OpportunityFormValues>(() => fromOpportunity(initial));
  const [agencies, setAgencies] = useState<Agency[]>([]);
  const [companies, setCompanies] = useState<Company[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    agenciesApi.list().then(setAgencies).catch(() => setAgencies([]));
    companiesApi.list().then(setCompanies).catch(() => setCompanies([]));
  }, []);

  function set<K extends keyof OpportunityFormValues>(key: K, value: string) {
    setValues((v) => ({ ...v, [key]: value }));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!values.title.trim()) {
      setError("Title is required.");
      return;
    }
    try {
      await onSubmit(toPayload(values));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save opportunity.");
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-5">
      <section className="grid grid-cols-2 gap-3">
        <Field label="Title" className="col-span-2">
          <Input value={values.title} onChange={(e) => set("title", e.target.value)} required />
        </Field>
        <Field label="Agency">
          <Select value={values.agency_id || undefined} onValueChange={(v) => set("agency_id", v)}>
            <SelectTrigger><SelectValue placeholder="Select agency" /></SelectTrigger>
            <SelectContent>
              {agencies.map((a) => (
                <SelectItem key={a.id} value={a.id}>{a.short_name ?? a.name}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
        <Field label="Solicitation Number">
          <Input value={values.solicitation_number} onChange={(e) => set("solicitation_number", e.target.value)} />
        </Field>
        <Field label="Location City">
          <Input value={values.location_city} onChange={(e) => set("location_city", e.target.value)} />
        </Field>
        <Field label="Location State">
          <Input value={values.location_state} maxLength={2} onChange={(e) => set("location_state", e.target.value)} />
        </Field>
        <Field label="NAICS Code">
          <Input value={values.naics_code} onChange={(e) => set("naics_code", e.target.value)} />
        </Field>
        <Field label="PSC Code">
          <Input value={values.psc_code} onChange={(e) => set("psc_code", e.target.value)} />
        </Field>
        <Field label="Set-Aside">
          <Select value={values.set_aside} onValueChange={(v) => set("set_aside", v)}>
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              {SET_ASIDES.map((s) => <SelectItem key={s} value={s}>{s.replace(/_/g, " ")}</SelectItem>)}
            </SelectContent>
          </Select>
        </Field>
        <Field label="Contract Type">
          <Select value={values.contract_type} onValueChange={(v) => set("contract_type", v)}>
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              {CONTRACT_TYPES.map((s) => <SelectItem key={s} value={s}>{s.replace(/_/g, " ")}</SelectItem>)}
            </SelectContent>
          </Select>
        </Field>
        <Field label="Opportunity Maturity">
          <Select value={values.maturity_stage} onValueChange={(v) => set("maturity_stage", v)}>
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              {MATURITY_STAGES.map((s) => <SelectItem key={s} value={s}>{s.replace(/_/g, " ")}</SelectItem>)}
            </SelectContent>
          </Select>
        </Field>
      </section>

      <section className="grid grid-cols-3 gap-3">
        <Field label="Est. Value (Low)">
          <Input type="number" value={values.estimated_value_low} onChange={(e) => set("estimated_value_low", e.target.value)} />
        </Field>
        <Field label="Est. Value (High)">
          <Input type="number" value={values.estimated_value_high} onChange={(e) => set("estimated_value_high", e.target.value)} />
        </Field>
        <Field label="Est. Principal Fee">
          <Input type="number" value={values.estimated_fee} onChange={(e) => set("estimated_fee", e.target.value)} />
        </Field>
        <Field label="Duration (months)">
          <Input type="number" value={values.contract_duration_months} onChange={(e) => set("contract_duration_months", e.target.value)} />
        </Field>
        <Field label="Opportunity Source">
          <Input value={values.opportunity_source_label} onChange={(e) => set("opportunity_source_label", e.target.value)} />
        </Field>
      </section>

      <section className="grid grid-cols-2 gap-3">
        <Field label="Proposal Due">
          <Input type="datetime-local" value={values.proposal_due_at} onChange={(e) => set("proposal_due_at", e.target.value)} />
        </Field>
        <Field label="Questions Due">
          <Input type="datetime-local" value={values.questions_due_at} onChange={(e) => set("questions_due_at", e.target.value)} />
        </Field>
        <Field label="Site Visit">
          <Input type="datetime-local" value={values.site_visit_at} onChange={(e) => set("site_visit_at", e.target.value)} />
        </Field>
        <Field label="Industry Day">
          <Input type="datetime-local" value={values.industry_day_at} onChange={(e) => set("industry_day_at", e.target.value)} />
        </Field>
        <Field label="Sources Sought Due">
          <Input type="datetime-local" value={values.sources_sought_due_at} onChange={(e) => set("sources_sought_due_at", e.target.value)} />
        </Field>
      </section>

      <section className="grid grid-cols-2 gap-3">
        <Field label="Incumbent">
          <Select value={values.incumbent_company_id || undefined} onValueChange={(v) => set("incumbent_company_id", v)}>
            <SelectTrigger><SelectValue placeholder="None on file" /></SelectTrigger>
            <SelectContent>
              {companies.map((c) => <SelectItem key={c.id} value={c.id}>{c.name}</SelectItem>)}
            </SelectContent>
          </Select>
        </Field>
        <Field label="Incumbent Notes">
          <Input value={values.incumbent_notes} onChange={(e) => set("incumbent_notes", e.target.value)} />
        </Field>
      </section>

      <section className="grid grid-cols-1 gap-3">
        <Field label="Description"><Textarea rows={3} value={values.description} onChange={(e) => set("description", e.target.value)} /></Field>
        <Field label="Scope Summary (used by the Pursuit Score's Strategic Fit)"><Textarea rows={2} value={values.scope_summary} onChange={(e) => set("scope_summary", e.target.value)} /></Field>
        <Field label="Evaluation Factors"><Textarea rows={2} value={values.evaluation_factors} onChange={(e) => set("evaluation_factors", e.target.value)} /></Field>
        <Field label="Past Performance Requirements"><Textarea rows={2} value={values.past_performance_requirements} onChange={(e) => set("past_performance_requirements", e.target.value)} /></Field>
        <Field label="Internal Notes"><Textarea rows={2} value={values.internal_notes} onChange={(e) => set("internal_notes", e.target.value)} /></Field>
      </section>

      {error && <p className="text-xs text-destructive">{error}</p>}
      <Button type="submit" disabled={busy}>{busy ? "Saving…" : submitLabel}</Button>
    </form>
  );
}

function Field({ label, children, className }: { label: string; children: React.ReactNode; className?: string }) {
  return (
    <div className={className}>
      <Label className="mb-1 block">{label}</Label>
      {children}
    </div>
  );
}
