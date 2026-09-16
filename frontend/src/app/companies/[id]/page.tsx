"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { companiesApi } from "@/lib/api/resources";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { SampleDataBadge } from "@/components/domain/badges";
import { LoadingState, ErrorState } from "@/components/ui/states";
import { titleCase } from "@/lib/utils";
import type { Company } from "@/types";

function Fact({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <div className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="mt-0.5 text-sm text-foreground">{value || "—"}</div>
    </div>
  );
}

export default function CompanyDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [company, setCompany] = useState<Company | null>(null);
  const [error, setError] = useState<string | null>(null);

  function load() {
    setError(null);
    companiesApi.get(id).then(setCompany).catch((e) => setError(e.message));
  }
  useEffect(load, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  if (error) return <ErrorState message={error} onRetry={load} />;
  if (!company) return <LoadingState />;

  const tags = [
    company.is_sdvosb && "SDVOSB", company.is_vosb && "VOSB", company.is_hubzone && "HUBZone",
    company.is_eight_a && "8(a)", company.is_wosb && "WOSB", company.is_edwosb && "EDWOSB",
    company.is_dbe && "DBE", company.is_small_business && "Small Business",
  ].filter(Boolean) as string[];

  return (
    <div className="flex flex-col gap-4">
      <div>
        <div className="flex items-center gap-2">
          <h1 className="text-xl font-semibold text-foreground">{company.name}</h1>
          {company.is_sample_data && <SampleDataBadge />}
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-1.5">
          <Badge variant="outline">{titleCase(company.company_type)}</Badge>
          {tags.map((t) => <Badge key={t} variant="secondary">{t}</Badge>)}
        </div>
      </div>

      <Card>
        <CardHeader><CardTitle>Company Profile</CardTitle></CardHeader>
        <CardContent className="grid grid-cols-2 gap-4 sm:grid-cols-3">
          <Fact label="Website" value={company.website} />
          <Fact label="Headquarters" value={company.headquarters_city ? `${company.headquarters_city}, ${company.headquarters_state}` : null} />
          <Fact label="Other Locations" value={company.other_locations} />
          <Fact label="NAICS Codes" value={company.naics_codes} />
          <Fact label="Relationship Strength" value={company.relationship_strength ? `${company.relationship_strength}/5` : null} />
        </CardContent>
        <CardContent className="grid grid-cols-1 gap-4 border-t border-border pt-4 sm:grid-cols-2">
          <Fact label="Technical Specialties" value={company.technical_specialties} />
          <Fact label="Federal Experience" value={company.federal_experience_summary} />
          <Fact label="Agencies Served" value={company.agencies_served} />
          <Fact label="Contract Vehicles" value={company.contract_vehicles} />
        </CardContent>
        {company.notes && (
          <CardContent className="border-t border-border pt-4">
            <Fact label="Notes" value={company.notes} />
          </CardContent>
        )}
      </Card>
    </div>
  );
}
