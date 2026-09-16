"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Radar, ExternalLink } from "lucide-react";
import { intelligenceApi, intelligenceItemsApi } from "@/lib/api/resources";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { LoadingState, ErrorState, EmptyState } from "@/components/ui/states";
import { SampleDataBadge, IntelligenceCategoryBadge, INTELLIGENCE_CATEGORY_LABELS, RelevanceTierBadge } from "@/components/domain/badges";
import { titleCase } from "@/lib/utils";
import type { IntelligenceItem, IntelligenceCategory, IntelligenceSource } from "@/types";

const CATEGORIES: IntelligenceCategory[] = ["live_opportunity", "pre_solicitation", "early_signal", "award_intelligence"];

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

  const [q, setQ] = useState("");
  const [category, setCategory] = useState(searchParams.get("category") ?? "");
  const [sourceId, setSourceId] = useState("");
  const [state, setState] = useState("");
  const [hideSampleData, setHideSampleData] = useState(false);
  const [samRelevanceTier, setSamRelevanceTier] = useState("relevant");
  const [grantsRelevanceTier, setGrantsRelevanceTier] = useState("relevant_signal");
  const [sortBy, setSortBy] = useState("first_detected_at");
  const [sortDir, setSortDir] = useState("desc");

  // Populates the Source filter dynamically — any enabled Source Registry row shows up
  // automatically, not just SAM.gov/Grants.gov/USAspending.gov, so a future connector
  // never needs a matching frontend change here.
  useEffect(() => {
    intelligenceApi.listSources().then((all) =>
      setSources(all.filter((s) => s.is_enabled).sort((a, b) => a.name.localeCompare(b.name)))
    );
  }, []);

  const params = useMemo(
    () => ({
      q: q || undefined, category: category || undefined, source_id: sourceId || undefined,
      state: state || undefined, include_sample_data: !hideSampleData, sam_relevance_tier: samRelevanceTier,
      grants_relevance_tier: grantsRelevanceTier, sort_by: sortBy, sort_dir: sortDir, limit: 200,
    }),
    [q, category, sourceId, state, hideSampleData, samRelevanceTier, grantsRelevanceTier, sortBy, sortDir]
  );

  function load() {
    setError(null);
    intelligenceItemsApi.list(params).then(setItems).catch((e) => setError(e.message));
  }
  useEffect(load, [params]); // eslint-disable-line react-hooks/exhaustive-deps

  if (error) return <ErrorState message={error} onRetry={load} />;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-foreground">Discover</h1>
          <p className="text-sm text-muted-foreground">
            Live opportunities, pre-solicitations, early signals, and award intelligence from every connected source.
            SAM.gov and Grants.gov records are both broadly retrieved for auditability but only shown here at
            Relevant/Relevant Signal or above by default — widen either Relevance filter to see lower-confidence
            matches or every record fetched. Grants.gov is an early-signal source for future engineering
            procurement, not a list of grants to apply for.
          </p>
        </div>
        <Link href="/sources">
          <Button variant="outline" size="sm"><Radar className="h-4 w-4" /> Manage Sources</Button>
        </Link>
      </div>

      <div className="flex flex-wrap gap-2 rounded-lg border border-border bg-secondary/40 p-2.5">
        <Input placeholder="Search title, agency, location…" value={q} onChange={(e) => setQ(e.target.value)} className="max-w-xs bg-card" />
        <Select value={category || "all"} onValueChange={(v) => setCategory(v === "all" ? "" : v)}>
          <SelectTrigger className="w-48"><SelectValue placeholder="Category" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All categories</SelectItem>
            {CATEGORIES.map((c) => <SelectItem key={c} value={c}>{INTELLIGENCE_CATEGORY_LABELS[c]}</SelectItem>)}
          </SelectContent>
        </Select>
        <Select value={sourceId || "all"} onValueChange={(v) => setSourceId(v === "all" ? "" : v)}>
          <SelectTrigger className="w-48"><SelectValue placeholder="Source" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Sources</SelectItem>
            {sources.map((s) => <SelectItem key={s.id} value={s.id}>{s.name}</SelectItem>)}
          </SelectContent>
        </Select>
        <Input placeholder="State (e.g. LA)" value={state} onChange={(e) => setState(e.target.value.toUpperCase())} className="w-32" maxLength={2} />
        <Select value={samRelevanceTier} onValueChange={setSamRelevanceTier}>
          <SelectTrigger className="w-56"><SelectValue /></SelectTrigger>
          <SelectContent>
            {SAM_RELEVANCE_TIER_OPTIONS.map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}
          </SelectContent>
        </Select>
        <Select value={grantsRelevanceTier} onValueChange={setGrantsRelevanceTier}>
          <SelectTrigger className="w-56"><SelectValue /></SelectTrigger>
          <SelectContent>
            {GRANTS_RELEVANCE_TIER_OPTIONS.map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}
          </SelectContent>
        </Select>
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
        <label className="flex items-center gap-1.5 rounded-md border border-input bg-card px-3 text-sm text-foreground">
          <input type="checkbox" checked={hideSampleData} onChange={(e) => setHideSampleData(e.target.checked)} />
          Hide sample data
        </label>
      </div>

      {!items ? (
        <LoadingState />
      ) : items.length === 0 ? (
        <EmptyState
          title="No intelligence yet"
          description="Sync a source on the Intelligence Sources page, or adjust your filters."
          action={<Link href="/sources"><Button size="sm">Go to Intelligence Sources</Button></Link>}
        />
      ) : (
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
              {items.map((item) => {
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
                        // Mutually exclusive in practice — an item comes from exactly one
                        // source, so at most one of these is ever non-null. The tier name
                        // (Highly Relevant / Relevant / etc.) is printed directly on the
                        // badge via RelevanceTierBadge, so a reader never has to mentally
                        // map a bare number to what it means, and the source label above
                        // it keeps this unmistakably separate from the Signal Score column.
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
