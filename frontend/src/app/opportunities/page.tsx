"use client";

import { useEffect, useState, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { opportunitiesApi } from "@/lib/api/resources";
import { OpportunityTable } from "@/components/opportunities/opportunity-table";
import { NewOpportunityDialog } from "@/components/opportunities/new-opportunity-dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { LoadingState, ErrorState } from "@/components/ui/states";
import { FilterChip } from "@/components/ui/filter-chip";
import type { OpportunityListItem } from "@/types";

const SET_ASIDES = ["unrestricted", "sdvosb", "small_business", "eight_a", "hubzone", "wosb", "edwosb", "other"];

// Mirrors the Dashboard KPI label a `kpi` URL param drilled down from — keep in sync
// with backend/app/services/dashboard_filters.py's KPI_FILTER_NAMES and page.tsx's own
// KpiCard labels, so the chip always reads exactly like the card the user clicked.
const KPI_LABELS: Record<string, string> = {
  due_soon: "Due Within 30 Days",
  awaiting_go_no_go: "Awaiting Go/No-Go",
  active_proposals: "Active Proposals",
  interviews_pending: "Interviews Pending",
  awards_pending: "Awards Pending",
  sdvosb: "SDVOSB Set-Asides",
  limited_competition: "Limited Competition",
  recompete: "Possible Recompetes",
  early_stage: "Early-Stage Signals",
  discovered_this_week: "Discovered This Week",
};

function OpportunitiesPageInner() {
  const searchParams = useSearchParams();
  const [items, setItems] = useState<OpportunityListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [q, setQ] = useState(searchParams.get("q") ?? "");
  const [setAside, setSetAside] = useState<string>("");
  const [sortBy, setSortBy] = useState("score");
  const [sortDir, setSortDir] = useState("desc");
  const [kpi, setKpi] = useState<string>(searchParams.get("kpi") ?? "");
  // Threaded straight through from the Dashboard link that sent the user here (or
  // absent on a manual visit, defaulting to the same "include samples" behavior the
  // rest of the app already defaults to) — never re-derived, so it can't drift from
  // the value the Dashboard's own count was computed with.
  const includeSampleData = searchParams.get("include_sample_data") !== "false";

  function load() {
    setError(null);
    opportunitiesApi
      .list({
        q: q || undefined,
        set_aside: setAside || undefined,
        kpi: kpi || undefined,
        include_sample_data: includeSampleData,
        sort_by: sortBy,
        sort_dir: sortDir,
        limit: 2000,
      })
      .then(setItems)
      .catch((e) => setError(e.message));
  }

  useEffect(load, [q, setAside, sortBy, sortDir, kpi]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-foreground">Opportunities</h1>
          <p className="text-sm text-muted-foreground">
            {items ? `${items.length} opportunit${items.length === 1 ? "y" : "ies"} · ` : ""}
            Search, filter, and prioritize the active pipeline.
          </p>
        </div>
        <NewOpportunityDialog />
      </div>

      {kpi && (
        <FilterChip label={`Dashboard filter: ${KPI_LABELS[kpi] ?? kpi}`} onClear={() => setKpi("")} />
      )}

      <div className="flex flex-wrap items-center gap-2">
        <Input
          placeholder="Search title, solicitation #, location…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          className="max-w-xs"
        />
        <Select value={setAside || "all"} onValueChange={(v) => setSetAside(v === "all" ? "" : v)}>
          <SelectTrigger className="w-48"><SelectValue placeholder="Set-Aside" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All set-asides</SelectItem>
            {SET_ASIDES.map((s) => <SelectItem key={s} value={s}>{s.replace(/_/g, " ")}</SelectItem>)}
          </SelectContent>
        </Select>
        <Select value={sortBy} onValueChange={setSortBy}>
          <SelectTrigger className="w-44"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="score">Sort: Pursuit Score</SelectItem>
            <SelectItem value="proposal_due_at">Sort: Proposal Due</SelectItem>
            <SelectItem value="created_at">Sort: Date Added</SelectItem>
            <SelectItem value="title">Sort: Title</SelectItem>
            <SelectItem value="estimated_fee">Sort: Estimated Fee</SelectItem>
          </SelectContent>
        </Select>
        <Select value={sortDir} onValueChange={setSortDir}>
          <SelectTrigger className="w-32"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="desc">Descending</SelectItem>
            <SelectItem value="asc">Ascending</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {error && <ErrorState message={error} onRetry={load} />}
      {!error && !items && <LoadingState />}
      {!error && items && (
        <div className="rounded-lg border border-border bg-card">
          <OpportunityTable opportunities={items} />
        </div>
      )}
    </div>
  );
}

export default function OpportunitiesPage() {
  return (
    <Suspense fallback={<LoadingState />}>
      <OpportunitiesPageInner />
    </Suspense>
  );
}
