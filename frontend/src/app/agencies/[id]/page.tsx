"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { agenciesApi, opportunitiesApi } from "@/lib/api/resources";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { SampleDataBadge } from "@/components/domain/badges";
import { OpportunityTable } from "@/components/opportunities/opportunity-table";
import { LoadingState, ErrorState } from "@/components/ui/states";
import type { Agency, OpportunityListItem } from "@/types";

export default function AgencyDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [agency, setAgency] = useState<Agency | null>(null);
  const [opportunities, setOpportunities] = useState<OpportunityListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  function load() {
    setError(null);
    agenciesApi.get(id).then(setAgency).catch((e) => setError(e.message));
    opportunitiesApi.list({ agency_id: id, limit: 100 }).then(setOpportunities).catch(() => setOpportunities([]));
  }
  useEffect(load, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  if (error) return <ErrorState message={error} onRetry={load} />;
  if (!agency) return <LoadingState />;

  return (
    <div className="flex flex-col gap-4">
      <div>
        <div className="flex items-center gap-2">
          <h1 className="text-xl font-semibold text-foreground">{agency.name}</h1>
          {agency.is_sample_data && <SampleDataBadge />}
        </div>
        <div className="mt-1 flex items-center gap-2">
          <Badge variant={agency.priority_tier === 1 ? "accent" : "muted"}>Priority Tier {agency.priority_tier}</Badge>
          {agency.agency_type && <Badge variant="outline">{agency.agency_type}</Badge>}
        </div>
      </div>

      {agency.offices.length > 0 && (
        <Card>
          <CardHeader><CardTitle>Offices</CardTitle></CardHeader>
          <CardContent className="flex flex-col gap-2">
            {agency.offices.map((o) => (
              <div key={o.id} className="text-sm text-foreground">
                {o.name} {o.city && o.state ? <span className="text-muted-foreground">— {o.city}, {o.state}</span> : null}
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader><CardTitle>Principal&apos;s Pursuits with This Agency</CardTitle></CardHeader>
        <CardContent className="p-0">
          {!opportunities ? <LoadingState /> : <OpportunityTable opportunities={opportunities} />}
        </CardContent>
      </Card>
    </div>
  );
}
