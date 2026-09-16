"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Radar, ExternalLink } from "lucide-react";
import { intelligenceItemsApi } from "@/lib/api/resources";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { LoadingState, ErrorState, EmptyState } from "@/components/ui/states";
import { SampleDataBadge } from "@/components/domain/badges";
import { titleCase } from "@/lib/utils";
import type { IntelligenceItem, IntelligenceCategory } from "@/types";

const CATEGORY_BADGE: Record<IntelligenceCategory, { variant: "success" | "accent" | "warning" | "secondary"; label: string }> = {
  live_opportunity: { variant: "success", label: "Live Opportunity" },
  pre_solicitation: { variant: "accent", label: "Pre-Solicitation" },
  early_signal: { variant: "warning", label: "Early Signal" },
  award_intelligence: { variant: "secondary", label: "Award Intelligence" },
};

const CATEGORIES: IntelligenceCategory[] = ["live_opportunity", "pre_solicitation", "early_signal", "award_intelligence"];

function formatDate(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleDateString(undefined, { dateStyle: "medium" });
}

function formatMoney(value: number | null): string {
  if (!value) return "—";
  return `$${value.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

export default function DiscoverPage() {
  const router = useRouter();
  const [items, setItems] = useState<IntelligenceItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [q, setQ] = useState("");
  const [category, setCategory] = useState("");
  const [state, setState] = useState("");
  const [hideSampleData, setHideSampleData] = useState(false);
  const [sortBy, setSortBy] = useState("first_detected_at");
  const [sortDir, setSortDir] = useState("desc");

  const params = useMemo(
    () => ({
      q: q || undefined, category: category || undefined, state: state || undefined,
      include_sample_data: !hideSampleData, sort_by: sortBy, sort_dir: sortDir, limit: 200,
    }),
    [q, category, state, hideSampleData, sortBy, sortDir]
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
          </p>
        </div>
        <Link href="/sources">
          <Button variant="outline" size="sm"><Radar className="h-4 w-4" /> Manage Sources</Button>
        </Link>
      </div>

      <div className="flex flex-wrap gap-2">
        <Input placeholder="Search title, agency, location…" value={q} onChange={(e) => setQ(e.target.value)} className="max-w-xs" />
        <Select value={category || "all"} onValueChange={(v) => setCategory(v === "all" ? "" : v)}>
          <SelectTrigger className="w-48"><SelectValue placeholder="Category" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All categories</SelectItem>
            {CATEGORIES.map((c) => <SelectItem key={c} value={c}>{CATEGORY_BADGE[c].label}</SelectItem>)}
          </SelectContent>
        </Select>
        <Input placeholder="State (e.g. LA)" value={state} onChange={(e) => setState(e.target.value.toUpperCase())} className="w-32" maxLength={2} />
        <Select value={sortBy} onValueChange={setSortBy}>
          <SelectTrigger className="w-52"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="first_detected_at">Sort: Newest Detected</SelectItem>
            <SelectItem value="proposal_due_at">Sort: Due Date</SelectItem>
            <SelectItem value="estimated_value_high">Sort: Estimated Value</SelectItem>
            <SelectItem value="funding_amount">Sort: Funding Amount</SelectItem>
            <SelectItem value="early_signal_score">Sort: Early Signal Score</SelectItem>
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
                <TableHead>Signal Score</TableHead>
                <TableHead>Detected</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((item) => {
                const badge = CATEGORY_BADGE[item.intelligence_category];
                const promoted = !!item.opportunity_id;
                return (
                  <TableRow
                    key={item.id}
                    className={promoted ? "cursor-pointer" : ""}
                    onClick={() => promoted && router.push(`/opportunities/${item.opportunity_id}`)}
                  >
                    <TableCell><Badge variant={badge.variant}>{badge.label}</Badge></TableCell>
                    <TableCell>
                      <div className="flex items-center gap-2 font-medium text-foreground">
                        {item.title} {item.is_sample_data && <SampleDataBadge />}
                      </div>
                      <div className="text-xs text-muted-foreground">
                        {[item.agency_name, item.location_city, item.location_state].filter(Boolean).join(" · ") || "—"}
                      </div>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">{item.source}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {formatDate(item.proposal_due_at || item.posted_at)}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {formatMoney(item.estimated_value_high ?? item.funding_amount)}
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
