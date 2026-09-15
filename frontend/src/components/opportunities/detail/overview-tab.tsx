"use client";

import { useState } from "react";
import { ExternalLink, Pencil } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { OpportunityForm } from "@/components/opportunities/opportunity-form";
import { opportunitiesApi } from "@/lib/api/resources";
import { formatCurrency, formatDateTime, titleCase } from "@/lib/utils";
import type { Opportunity } from "@/types";

function Fact({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <div className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="mt-0.5 text-sm text-foreground">{value || "—"}</div>
    </div>
  );
}

export function OverviewTab({ opportunity, onUpdated }: { opportunity: Opportunity; onUpdated: (o: Opportunity) => void }) {
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
      <Card className="lg:col-span-2">
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle>Opportunity Details</CardTitle>
          <Button variant="outline" size="sm" onClick={() => setEditing(true)}>
            <Pencil className="h-3.5 w-3.5" /> Edit
          </Button>
        </CardHeader>
        <CardContent className="grid grid-cols-2 gap-4 sm:grid-cols-3">
          <Fact label="Agency" value={opportunity.agency?.name} />
          <Fact label="NAICS" value={opportunity.naics_code} />
          <Fact label="PSC" value={opportunity.psc_code} />
          <Fact label="Contract Type" value={titleCase(opportunity.contract_type)} />
          <Fact label="Est. Value (Low)" value={formatCurrency(opportunity.estimated_value_low)} />
          <Fact label="Est. Value (High)" value={formatCurrency(opportunity.estimated_value_high)} />
          <Fact label="Est. Principal Fee" value={formatCurrency(opportunity.estimated_fee)} />
          <Fact label="Duration" value={opportunity.contract_duration_months ? `${opportunity.contract_duration_months} months` : null} />
          <Fact label="Proposal Due" value={formatDateTime(opportunity.proposal_due_at)} />
          <Fact label="Questions Due" value={formatDateTime(opportunity.questions_due_at)} />
          <Fact label="Site Visit" value={formatDateTime(opportunity.site_visit_at)} />
          <Fact label="Industry Day" value={formatDateTime(opportunity.industry_day_at)} />
          <Fact label="Sources Sought Due" value={formatDateTime(opportunity.sources_sought_due_at)} />
          <Fact label="Incumbent Notes" value={opportunity.incumbent_notes} />
        </CardContent>
        {opportunity.description && (
          <CardContent className="border-t border-border pt-4">
            <div className="text-[11px] uppercase tracking-wide text-muted-foreground">Description</div>
            <p className="mt-1 whitespace-pre-wrap text-sm text-foreground">{opportunity.description}</p>
          </CardContent>
        )}
        {opportunity.scope_summary && (
          <CardContent className="border-t border-border pt-4">
            <div className="text-[11px] uppercase tracking-wide text-muted-foreground">Scope Summary</div>
            <p className="mt-1 whitespace-pre-wrap text-sm text-foreground">{opportunity.scope_summary}</p>
          </CardContent>
        )}
        {opportunity.evaluation_factors && (
          <CardContent className="border-t border-border pt-4">
            <div className="text-[11px] uppercase tracking-wide text-muted-foreground">Evaluation Factors</div>
            <p className="mt-1 whitespace-pre-wrap text-sm text-foreground">{opportunity.evaluation_factors}</p>
          </CardContent>
        )}
        {opportunity.past_performance_requirements && (
          <CardContent className="border-t border-border pt-4">
            <div className="text-[11px] uppercase tracking-wide text-muted-foreground">Past Performance Requirements</div>
            <p className="mt-1 whitespace-pre-wrap text-sm text-foreground">{opportunity.past_performance_requirements}</p>
          </CardContent>
        )}
        {opportunity.internal_notes && (
          <CardContent className="border-t border-border pt-4">
            <div className="text-[11px] uppercase tracking-wide text-muted-foreground">Internal Notes</div>
            <p className="mt-1 whitespace-pre-wrap text-sm text-foreground">{opportunity.internal_notes}</p>
          </CardContent>
        )}
      </Card>

      <Card>
        <CardHeader><CardTitle>Data Provenance</CardTitle></CardHeader>
        <CardContent className="flex flex-col gap-3">
          <Fact label="Source" value={opportunity.opportunity_source_label} />
          <Fact label="Confidence" value={titleCase(opportunity.confidence)} />
          <Fact label="Retrieved" value={formatDateTime(opportunity.retrieved_at)} />
          <Fact label="Last Updated" value={formatDateTime(opportunity.updated_at)} />
          {opportunity.source_url && (
            <a
              href={opportunity.source_url}
              target="_blank"
              rel="noreferrer"
              className="flex items-center gap-1 text-xs font-medium text-primary hover:underline"
            >
              View Source <ExternalLink className="h-3 w-3" />
            </a>
          )}
        </CardContent>
      </Card>

      <Dialog open={editing} onOpenChange={setEditing}>
        <DialogContent className="max-w-2xl">
          <DialogHeader><DialogTitle>Edit Opportunity</DialogTitle></DialogHeader>
          <OpportunityForm
            initial={opportunity}
            submitLabel="Save Changes"
            busy={busy}
            onSubmit={async (payload) => {
              setBusy(true);
              try {
                const updated = await opportunitiesApi.update(opportunity.id, payload);
                onUpdated(updated);
                setEditing(false);
              } finally {
                setBusy(false);
              }
            }}
          />
        </DialogContent>
      </Dialog>
    </div>
  );
}
