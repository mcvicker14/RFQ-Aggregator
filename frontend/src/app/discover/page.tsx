"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import {
  Radar,
  ExternalLink,
  ChevronDown,
  ChevronUp,
  SlidersHorizontal,
  LayoutGrid,
  Table2,
  CircleDot,
  Clock,
  TrendingUp,
  Landmark,
} from "lucide-react";
import { agenciesApi, intelligenceApi, intelligenceItemsApi, opportunitiesApi } from "@/lib/api/resources";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { LoadingState, ErrorState, EmptyState } from "@/components/ui/states";
import { SampleDataBadge, IntelligenceCategoryBadge, INTELLIGENCE_CATEGORY_LABELS, RelevanceTierBadge } from "@/components/domain/badges";
import { FilterChip } from "@/components/ui/filter-chip";
import { IntelligenceCard } from "@/components/discover/intelligence-card";
import { cn, daysUntil, titleCase } from "@/lib/utils";
import type { Agency, IntelligenceItem, IntelligenceCategory, IntelligenceSource } from "@/types";

const CATEGORIES: IntelligenceCategory[] = ["live_opportunity", "pre_solicitation", "early_signal", "award_intelligence"];

// The Discover-specific, fuller phrasing for each category section (distinct from the
// terser badge labels in components/domain/badges.tsx) — this is the "different kinds
// of intelligence" distinction the page is organized around, so it gets the fuller name.
const CATEGORY_META: Record<IntelligenceCategory, { label: string; blurb: string; icon: typeof CircleDot; tone: string }> = {
  live_opportunity: { label: "Live Opportunities", blurb: "Open solicitations Principal can respond to now.", icon: CircleDot, tone: "text-success" },
  pre_solicitation: { label: "Pre-Solicitations / Sources Sought", blurb: "Early positioning window, before the formal solicitation drops.", icon: Clock, tone: "text-accent-foreground" },
  early_signal: { label: "Early Signals", blurb: "Market and funding activity that may become real work later.", icon: TrendingUp, tone: "text-warning" },
  award_intelligence: { label: "Award / Competitor Intelligence", blurb: "Who's winning what — recompete timing and the competitive landscape.", icon: Landmark, tone: "text-muted-foreground" },
};

const SAM_RELEVANCE_TIER_OPTIONS = [
  { value: "highly_relevant", label: "SAM: Highly Relevant (80+)" },
  { value: "relevant", label: "SAM: Relevant (65+) — default" },
  { value: "possible_match", label: "SAM: Possible Match (50+)" },
  { value: "all", label: "SAM: All Records" },
];

const GRANTS_RELEVANCE_TIER_OPTIONS = [
  { value: "high_value_signal", label: "Grants: High-Value Signal (80+)" },
  { value: "relevant_signal", label: "Grants: Relevant Signal (65+) — default" },
  { value: "possible_signal", label: "Grants: Possible Signal (50+)" },
  { value: "all", label: "Grants: All Records" },
];

const DEADLINE_OPTIONS = [
  { value: "any", label: "Any time" },
  { value: "overdue", label: "Past due" },
  { value: "7", label: "Due within 7 days" },
  { value: "30", label: "Due within 30 days" },
  { value: "90", label: "Due within 90 days" },
  { value: "none", label: "No deadline set" },
];

function matchesDeadline(item: IntelligenceItem, filter: string): boolean {
  if (filter === "any") return true;
  const due = daysUntil(item.proposal_due_at);
  if (filter === "none") return due === null;
  if (due === null) return false;
  if (filter === "overdue") return due < 0;
  return due >= 0 && due <= Number(filter);
}

function formatDate(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleDateString(undefined, { dateStyle: "medium" });
}

function formatMoney(value: number | null): string {
  if (!value) return "—";
  return `$${value.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

function DiscoverPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [items, setItems] = useState<IntelligenceItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sources, setSources] = useState<IntelligenceSource[]>([]);
  const [agencies, setAgencies] = useState<Agency[]>([]);

  const [q, setQ] = useState("");
  const [category, setCategory] = useState(searchParams.get("category") ?? "");
  const [view, setView] = useState<"cards" | "table">("cards");
  const [showMoreFilters, setShowMoreFilters] = useState(false);
  const [sourceId, setSourceId] = useState("");
  const [agencyId, setAgencyId] = useState("");
  const [state, setState] = useState("");
  const [deadline, setDeadline] = useState("any");
  // Reads the exact sample-data visibility a Dashboard link was built with (absent on
  // a manual visit, defaulting to the same "include samples" behavior as elsewhere) —
  // never re-derived, so this page's count can't drift from the number that linked here.
  const [hideSampleData, setHideSampleData] = useState(searchParams.get("include_sample_data") === "false");
  const [samRelevanceTier, setSamRelevanceTier] = useState("relevant");
  const [grantsRelevanceTier, setGrantsRelevanceTier] = useState("relevant_signal");
  const [sortBy, setSortBy] = useState("first_detected_at");
  const [sortDir, setSortDir] = useState("desc");

  // Populates the Source and Agency filters dynamically — any enabled Source Registry
  // row / any agency shows up automatically, no matching frontend change needed later.
  useEffect(() => {
    intelligenceApi.listSources().then((all) =>
      setSources(all.filter((s) => s.is_enabled).sort((a, b) => a.name.localeCompare(b.name)))
    );
    agenciesApi.list().then((all) => setAgencies([...all].sort((a, b) => a.name.localeCompare(b.name))));
  }, []);

  const params = useMemo(
    () => ({
      q: q || undefined, category: category || undefined, source_id: sourceId || undefined,
      agency_id: agencyId || undefined, state: state || undefined, include_sample_data: !hideSampleData,
      sam_relevance_tier: samRelevanceTier, grants_relevance_tier: grantsRelevanceTier,
      sort_by: sortBy, sort_dir: sortDir, limit: 2000,
    }),
    [q, category, sourceId, agencyId, state, hideSampleData, samRelevanceTier, grantsRelevanceTier, sortBy, sortDir]
  );

  function load() {
    setError(null);
    intelligenceItemsApi.list(params).then(setItems).catch((e) => setError(e.message));
  }
  useEffect(load, [params]); // eslint-disable-line react-hooks/exhaustive-deps

  const filteredItems = useMemo(
    () => items?.filter((item) => matchesDeadline(item, deadline)) ?? null,
    [items, deadline]
  );

  const byCategory = useMemo(() => {
    const map = new Map<IntelligenceCategory, IntelligenceItem[]>();
    CATEGORIES.forEach((c) => map.set(c, []));
    (filteredItems ?? []).forEach((item) => map.get(item.intelligence_category)?.push(item));
    return map;
  }, [filteredItems]);

  async function handleTrack(item: IntelligenceItem) {
    const payload: Record<string, unknown> = {
      title: item.title,
      source_intelligence_item_id: item.id,
      opportunity_source_label: item.source,
    };
    if (item.agency_id) payload.agency_id = item.agency_id;
    if (item.solicitation_number) payload.solicitation_number = item.solicitation_number;
    if (item.location_city) payload.location_city = item.location_city;
    if (item.location_state) payload.location_state = item.location_state;
    if (item.naics_code) payload.naics_code = item.naics_code;
    if (item.psc_code) payload.psc_code = item.psc_code;
    if (item.set_aside) payload.set_aside = item.set_aside;
    if (item.proposal_due_at) payload.proposal_due_at = item.proposal_due_at;
    if (item.maturity_stage) payload.maturity_stage = item.maturity_stage;
    if (item.estimated_value_low) payload.estimated_value_low = item.estimated_value_low;
    if (item.estimated_value_high) payload.estimated_value_high = item.estimated_value_high;

    const created = await opportunitiesApi.create(payload);
    setItems((prev) => prev?.map((i) => (i.id === item.id ? { ...i, opportunity_id: created.id } : i)) ?? prev);
  }

  if (error) return <ErrorState message={error} onRetry={load} />;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-foreground">Discover</h1>
          <p className="text-sm text-muted-foreground">Market intelligence, upcoming procurements, and early signals.</p>
        </div>
        <Link href="/sources">
          <Button variant="outline" size="sm"><Radar className="h-4 w-4" /> Manage Sources</Button>
        </Link>
      </div>

      {category && (
        <FilterChip
          label={`Dashboard filter: ${INTELLIGENCE_CATEGORY_LABELS[category] ?? category}`}
          onClear={() => setCategory("")}
        />
      )}

      {/* Category quick-filter strip — the "different kinds of intelligence" distinction
          is visible before a user even opens a dropdown. Clicking a chip again clears it. */}
      <div className="flex flex-wrap gap-2">
        {CATEGORIES.map((c) => {
          const meta = CATEGORY_META[c];
          const Icon = meta.icon;
          const count = byCategory.get(c)?.length ?? 0;
          const active = category === c;
          return (
            <button
              key={c}
              type="button"
              onClick={() => setCategory(active ? "" : c)}
              className={cn(
                "flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition-colors",
                active ? "border-primary bg-primary text-primary-foreground" : "border-border bg-card text-foreground hover:border-primary/30 hover:bg-secondary/60"
              )}
            >
              <Icon className={cn("h-3.5 w-3.5", !active && meta.tone)} />
              {meta.label}
              <span className={cn("tabular-nums", active ? "opacity-80" : "text-muted-foreground")}>{count}</span>
            </button>
          );
        })}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Input placeholder="Search title, agency, location…" value={q} onChange={(e) => setQ(e.target.value)} className="max-w-xs" />
        <Select value={sortBy} onValueChange={setSortBy}>
          <SelectTrigger className="w-52"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="first_detected_at">Sort: Newest Detected</SelectItem>
            <SelectItem value="proposal_due_at">Sort: Due Date</SelectItem>
            <SelectItem value="estimated_value_high">Sort: Estimated Value</SelectItem>
            <SelectItem value="funding_amount">Sort: Funding Amount</SelectItem>
            <SelectItem value="early_signal_score">Sort: Early Signal Score</SelectItem>
            <SelectItem value="sam_relevance_score">Sort: SAM Relevance Score</SelectItem>
            <SelectItem value="grants_relevance_score">Sort: Grant Engineering Relevance Score</SelectItem>
            <SelectItem value="pursuit_score">Sort: Principal Pursuit Score</SelectItem>
          </SelectContent>
        </Select>
        <Select value={sortDir} onValueChange={setSortDir}>
          <SelectTrigger className="w-32"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="desc">Descending</SelectItem>
            <SelectItem value="asc">Ascending</SelectItem>
          </SelectContent>
        </Select>

        <Button variant="outline" size="sm" onClick={() => setShowMoreFilters((v) => !v)}>
          <SlidersHorizontal className="h-3.5 w-3.5" /> More Filters
          {showMoreFilters ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
        </Button>

        <div className="ml-auto flex rounded-md border border-border p-0.5">
          <Button variant={view === "cards" ? "secondary" : "ghost"} size="sm" onClick={() => setView("cards")}>
            <LayoutGrid className="h-3.5 w-3.5" /> Cards
          </Button>
          <Button variant={view === "table" ? "secondary" : "ghost"} size="sm" onClick={() => setView("table")}>
            <Table2 className="h-3.5 w-3.5" /> Table
          </Button>
        </div>
      </div>

      {showMoreFilters && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-secondary/40 p-2.5">
          <Select value={sourceId || "all"} onValueChange={(v) => setSourceId(v === "all" ? "" : v)}>
            <SelectTrigger className="w-48 bg-card"><SelectValue placeholder="Source" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Sources</SelectItem>
              {sources.map((s) => <SelectItem key={s.id} value={s.id}>{s.name}</SelectItem>)}
            </SelectContent>
          </Select>
          <Select value={agencyId || "all"} onValueChange={(v) => setAgencyId(v === "all" ? "" : v)}>
            <SelectTrigger className="w-48 bg-card"><SelectValue placeholder="Agency" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Agencies</SelectItem>
              {agencies.map((a) => <SelectItem key={a.id} value={a.id}>{a.short_name || a.name}</SelectItem>)}
            </SelectContent>
          </Select>
          <Input placeholder="State (e.g. LA)" value={state} onChange={(e) => setState(e.target.value.toUpperCase())} className="w-32 bg-card" maxLength={2} />
          <Select value={deadline} onValueChange={setDeadline}>
            <SelectTrigger className="w-44 bg-card"><SelectValue /></SelectTrigger>
            <SelectContent>
              {DEADLINE_OPTIONS.map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}
            </SelectContent>
          </Select>
          <Select value={samRelevanceTier} onValueChange={setSamRelevanceTier}>
            <SelectTrigger className="w-56 bg-card"><SelectValue /></SelectTrigger>
            <SelectContent>
              {SAM_RELEVANCE_TIER_OPTIONS.map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}
            </SelectContent>
          </Select>
          <Select value={grantsRelevanceTier} onValueChange={setGrantsRelevanceTier}>
            <SelectTrigger className="w-56 bg-card"><SelectValue /></SelectTrigger>
            <SelectContent>
              {GRANTS_RELEVANCE_TIER_OPTIONS.map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}
            </SelectContent>
          </Select>
          <label className="flex items-center gap-1.5 rounded-md border border-input bg-card px-3 py-1.5 text-sm text-foreground">
            <input type="checkbox" checked={hideSampleData} onChange={(e) => setHideSampleData(e.target.checked)} />
            Hide sample data
          </label>
          <p className="basis-full text-xs text-muted-foreground">
            SAM.gov and Grants.gov records are broadly retrieved for auditability but only shown here at Relevant/Relevant
            Signal or above by default — widen either Relevance filter to see lower-confidence matches or every record
            fetched. Grants.gov is an early-signal source for future engineering procurement, not a list of grants to
            apply for.
          </p>
        </div>
      )}

      {!filteredItems ? (
        <LoadingState />
      ) : filteredItems.length === 0 ? (
        <EmptyState
          title="No intelligence yet"
          description="Sync a source on the Intelligence Sources page, or adjust your filters."
          action={<Link href="/sources"><Button size="sm">Go to Intelligence Sources</Button></Link>}
        />
      ) : view === "table" ? (
        <Card>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Category</TableHead>
                <TableHead>Opportunity</TableHead>
                <TableHead>Source</TableHead>
                <TableHead>Key Date</TableHead>
                <TableHead>Value / Funding</TableHead>
                <TableHead title="Could this plausibly lead to engineering work for Principal? SAM.gov and Grants.gov each have their own Relevance score, shown with its own label per row.">
                  Relevance
                </TableHead>
                <TableHead title="How mature/actionable this early signal is — a different question from Relevance, which asks whether the signal is even worth Principal's attention in the first place.">
                  Signal Score
                </TableHead>
                <TableHead>Detected</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filteredItems.map((item) => {
                const promoted = !!item.opportunity_id;
                return (
                  <TableRow
                    key={item.id}
                    className={promoted ? "cursor-pointer" : ""}
                    onClick={() => promoted && router.push(`/opportunities/${item.opportunity_id}`)}
                  >
                    <TableCell><IntelligenceCategoryBadge value={item.intelligence_category} /></TableCell>
                    <TableCell>
                      <div className="flex items-center gap-2 font-medium text-foreground">
                        {item.title} {item.is_sample_data && <SampleDataBadge />}
                      </div>
                      <div className="text-xs text-muted-foreground">
                        {[item.agency_name, item.location_city, item.location_state].filter(Boolean).join(" · ") || "—"}
                      </div>
                      {(item.sam_relevance_rationale || item.grants_relevance_rationale) && (() => {
                        const rationale = item.sam_relevance_rationale ?? item.grants_relevance_rationale!;
                        return (
                          <div
                            className="mt-0.5 max-w-md truncate text-xs text-muted-foreground"
                            title={
                              rationale.why_not_fit
                                ? `${rationale.why_relevant} ${rationale.why_not_fit}`
                                : rationale.why_relevant
                            }
                          >
                            {rationale.why_relevant}
                          </div>
                        );
                      })()}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">{item.source}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {formatDate(item.proposal_due_at || item.posted_at)}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {formatMoney(item.estimated_value_high ?? item.funding_amount)}
                    </TableCell>
                    <TableCell>
                      {(() => {
                        if (item.grants_relevance_score !== null) {
                          return (
                            <div
                              className="flex flex-col items-start gap-1"
                              title="Grant Engineering Relevance Score — could this plausibly lead to engineering work for Principal?"
                            >
                              <span className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
                                Grant Relevance
                              </span>
                              <RelevanceTierBadge
                                tier={item.grants_relevance_rationale?.tier ?? "unscored"}
                                score={item.grants_relevance_score}
                              />
                            </div>
                          );
                        }
                        if (item.sam_relevance_score !== null) {
                          return (
                            <div
                              className="flex flex-col items-start gap-1"
                              title="SAM Relevance Score — is this SAM.gov notice even worth Principal's attention?"
                            >
                              <span className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
                                SAM Relevance
                              </span>
                              <RelevanceTierBadge
                                tier={item.sam_relevance_rationale?.tier ?? "unscored"}
                                score={item.sam_relevance_score}
                              />
                            </div>
                          );
                        }
                        return <span className="text-xs text-muted-foreground">—</span>;
                      })()}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {item.early_signal_score !== null ? `${item.early_signal_score}/100` : "—"}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      <div className="flex items-center gap-2">
                        {formatDate(item.first_detected_at)}
                        {!promoted && item.source_url && (
                          <a
                            href={item.source_url}
                            target="_blank"
                            rel="noreferrer"
                            onClick={(e) => e.stopPropagation()}
                            className="text-primary hover:underline"
                            title="View source"
                          >
                            <ExternalLink className="h-3.5 w-3.5" />
                          </a>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </Card>
      ) : (
        <div className="flex flex-col gap-6">
          {CATEGORIES.map((c) => {
            const categoryItems = byCategory.get(c) ?? [];
            if (categoryItems.length === 0) return null;
            const meta = CATEGORY_META[c];
            const Icon = meta.icon;
            return (
              <div key={c}>
                <div className="mb-2.5 flex items-baseline gap-2">
                  <h2 className={cn("flex items-center gap-1.5 text-sm font-semibold", meta.tone)}>
                    <Icon className="h-4 w-4" /> {meta.label}
                    <span className="text-muted-foreground">({categoryItems.length})</span>
                  </h2>
                  <span className="text-xs text-muted-foreground">— {meta.blurb}</span>
                </div>
                <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
                  {categoryItems.map((item) => (
                    <IntelligenceCard key={item.id} item={item} onTrack={handleTrack} />
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default function DiscoverPage() {
  return (
    <Suspense fallback={<LoadingState />}>
      <DiscoverPageInner />
    </Suspense>
  );
}
