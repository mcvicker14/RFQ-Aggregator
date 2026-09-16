"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  Briefcase,
  DollarSign,
  CalendarClock,
  Gavel,
  FileEdit,
  TrendingUp,
  Radar,
  CircleDot,
  Clock,
  Landmark,
  AlertTriangle,
  Bell,
} from "lucide-react";
import { dashboardApi } from "@/lib/api/resources";
import { KpiCard } from "@/components/dashboard/kpi-card";
import { CompactStat } from "@/components/dashboard/compact-stat";
import { HorizontalBarChartCard, TrendChartCard } from "@/components/dashboard/charts";
import { OpportunityTable } from "@/components/opportunities/opportunity-table";
import { TaskStatusBadge, PriorityBadge, contractTypeLabel } from "@/components/domain/badges";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { LoadingState, ErrorState, EmptyState } from "@/components/ui/states";
import { formatCurrency, formatDate } from "@/lib/utils";
import type { DashboardSummary } from "@/types";

// Every clickable KPI below links to /opportunities or /discover using the exact same
// named filter (see backend/app/services/dashboard_filters.py) the Dashboard's own
// count was computed with — never a second, separately-maintained definition of "what
// this number means" — and a zero count renders the card non-interactive rather than
// linking to a destination the user already knows is empty.
function hrefIf(count: number, href: string): string | undefined {
  return count > 0 ? href : undefined;
}

function oppHref(kpi: string | undefined, includeSamples: boolean): string {
  const usp = new URLSearchParams();
  if (kpi) usp.set("kpi", kpi);
  if (!includeSamples) usp.set("include_sample_data", "false");
  const qs = usp.toString();
  return qs ? `/opportunities?${qs}` : "/opportunities";
}

function discoverHref(category: string, includeSamples: boolean): string {
  const usp = new URLSearchParams({ category });
  if (!includeSamples) usp.set("include_sample_data", "false");
  return `/discover?${usp.toString()}`;
}

export default function DashboardPage() {
  const [data, setData] = useState<DashboardSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  function load() {
    setLoading(true);
    setError(null);
    dashboardApi
      .summary()
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }

  useEffect(load, []);

  if (loading) return <LoadingState label="Loading dashboard…" />;
  if (error) return <ErrorState message={error} onRetry={load} />;
  if (!data) return null;

  const { kpis, intelligence: intel, include_samples: includeSamples } = data;
  const today = new Date();

  return (
    <div className="flex flex-col gap-8">
      <div>
        <h1 className="text-xl font-semibold tracking-tight text-foreground">Executive Dashboard</h1>
        <p className="text-sm text-muted-foreground">
          {today.toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric", year: "numeric" })} — Principal
          Engineering business-development pipeline health.
        </p>
      </div>

      {/* Tier 1 — primary executive row: the headline numbers, full-size cards, no
          section chrome needed since prominence itself signals "read this first." */}
      <div className="flex flex-col gap-4">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          <KpiCard
            label="Active Opportunities"
            value={kpis.total_active_opportunities}
            icon={Briefcase}
            href={hrefIf(kpis.total_active_opportunities, oppHref(undefined, includeSamples))}
          />
          <KpiCard
            label="Awaiting Go/No-Go"
            value={kpis.awaiting_go_no_go}
            icon={Gavel}
            tone={kpis.awaiting_go_no_go > 0 ? "warning" : "default"}
            href={hrefIf(kpis.awaiting_go_no_go, oppHref("awaiting_go_no_go", includeSamples))}
          />
          <KpiCard
            label="Active Proposals"
            value={kpis.active_proposals}
            icon={FileEdit}
            href={hrefIf(kpis.active_proposals, oppHref("active_proposals", includeSamples))}
          />
          <KpiCard
            label="Due Within 30 Days"
            value={kpis.due_within_30_days}
            icon={CalendarClock}
            tone={kpis.due_within_30_days > 0 ? "warning" : "default"}
            href={hrefIf(kpis.due_within_30_days, oppHref("due_soon", includeSamples))}
          />
          <KpiCard
            label="Early Signals"
            value={intel.early_signal_count}
            icon={TrendingUp}
            tone="warning"
            href={hrefIf(intel.early_signal_count, discoverHref("early_signal", includeSamples))}
          />
        </div>

        {/* Tier 2 — business value: dollar totals, not tied to one filtered record set
            the same way a count is, so these stay informational rather than links. */}
        <div>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">Business Value</h3>
          <div className="grid grid-cols-2 gap-3 sm:max-w-md">
            <KpiCard
              label="Total Contract Value"
              value={formatCurrency(kpis.total_estimated_contract_value, { compact: true })}
              icon={DollarSign}
            />
            <KpiCard
              label="Est. Principal Fees"
              value={formatCurrency(kpis.total_estimated_fee, { compact: true })}
              icon={DollarSign}
              tone="accent"
            />
          </div>
        </div>
      </div>

      {/* Tier 3 — secondary/attention: compact chips, still all clickable. */}
      <div>
        <h3 className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          <AlertTriangle className="h-3.5 w-3.5" /> Needs Attention
        </h3>
        <div className="flex flex-wrap gap-2">
          <CompactStat
            label="Interviews Pending"
            value={kpis.interviews_pending}
            href={hrefIf(kpis.interviews_pending, oppHref("interviews_pending", includeSamples))}
          />
          <CompactStat
            label="Awards Pending"
            value={kpis.awards_pending}
            tone={kpis.awards_pending > 0 ? "warning" : "default"}
            href={hrefIf(kpis.awards_pending, oppHref("awards_pending", includeSamples))}
          />
          <CompactStat
            label="SDVOSB Set-Asides"
            value={kpis.sdvosb_setaside_count}
            tone="success"
            href={hrefIf(kpis.sdvosb_setaside_count, oppHref("sdvosb", includeSamples))}
          />
          <CompactStat
            label="Possible Recompetes"
            value={kpis.recompete_count}
            href={hrefIf(kpis.recompete_count, oppHref("recompete", includeSamples))}
          />
          <CompactStat
            label="Sources With Errors"
            value={intel.sources_with_errors}
            tone={intel.sources_with_errors > 0 ? "destructive" : "default"}
            href={hrefIf(intel.sources_with_errors, "/sources?health=error")}
          />
        </div>
      </div>

      {/* Tier 4 — moved out of main emphasis: still fully present, most compact. */}
      <div>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">More Metrics</h3>
        <div className="flex flex-wrap gap-2">
          <CompactStat label="Wins" value={kpis.wins} tone="success" />
          <CompactStat label="Losses" value={kpis.losses} tone="destructive" />
          <CompactStat label="Win Rate" value={kpis.win_rate_pct !== null ? `${kpis.win_rate_pct.toFixed(0)}%` : "—"} />
          <CompactStat
            label="Limited Competition"
            value={kpis.sole_source_or_limited_competition_count}
            href={hrefIf(kpis.sole_source_or_limited_competition_count, oppHref("limited_competition", includeSamples))}
          />
          <CompactStat
            label="Early-Stage Signals"
            value={kpis.early_stage_count}
            href={hrefIf(kpis.early_stage_count, oppHref("early_stage", includeSamples))}
          />
          <CompactStat label="Discovered This Week" value={kpis.discovered_this_week} />
          <CompactStat label="Sources Checked Today" value={intel.sources_checked_today} />
          <CompactStat label="New This Week" value={intel.new_this_week} />
        </div>
      </div>

      <div>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="flex items-center gap-1.5 text-sm font-semibold text-foreground"><Radar className="h-4 w-4" /> Intelligence</h2>
          <Link href="/discover" className="text-xs font-medium text-primary hover:underline">Open Discover</Link>
        </div>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <KpiCard
            label="Live Opportunities"
            value={intel.live_opportunity_count}
            icon={CircleDot}
            tone="success"
            href={hrefIf(intel.live_opportunity_count, discoverHref("live_opportunity", includeSamples))}
          />
          <KpiCard
            label="Pre-Solicitations"
            value={intel.pre_solicitation_count}
            icon={Clock}
            href={hrefIf(intel.pre_solicitation_count, discoverHref("pre_solicitation", includeSamples))}
          />
          <KpiCard
            label="Award Intelligence"
            value={intel.award_intelligence_count}
            icon={Landmark}
            href={hrefIf(intel.award_intelligence_count, discoverHref("award_intelligence", includeSamples))}
          />
        </div>
        {intel.new_intelligence_since_last_view > 0 && (
          <div className="mt-2 flex items-center gap-2 rounded-md bg-accent/10 px-3 py-2 text-xs text-accent-foreground">
            <Bell className="h-3.5 w-3.5" />
            {intel.new_intelligence_since_last_view} new intelligence item(s) since your last visit
            {intel.last_viewed_at && ` on ${formatDate(intel.last_viewed_at)}`}.
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <TrendChartCard title="Pipeline Value Over Time (Est. Fee)" data={data.pipeline_value_over_time} />
        <HorizontalBarChartCard title="Pipeline by Agency" data={data.pipeline_by_agency} />
        <HorizontalBarChartCard title="Pipeline by Stage" data={data.pipeline_by_stage} />
        <HorizontalBarChartCard title="Pipeline by State" data={data.pipeline_by_state} />
        <HorizontalBarChartCard title="Pipeline by Source" data={data.pipeline_by_source} />
        <HorizontalBarChartCard title="Pipeline by NAICS Code" data={data.pipeline_by_naics} />
        <HorizontalBarChartCard
          title="Pipeline by Contract Type"
          data={data.pipeline_by_contract_type.map((b) => ({ ...b, label: contractTypeLabel(b.label) }))}
        />
        <HorizontalBarChartCard
          title="Pipeline by Pursuit Score Band"
          data={data.pipeline_by_score_band.map((b) => ({ ...b, label: b.label === "unscored" ? "Not Scored" : `${b.label.charAt(0).toUpperCase()}${b.label.slice(1)} Priority` }))}
        />
      </div>

      <Card>
        <CardHeader className="flex-row items-center justify-between p-5 pb-0">
          <CardTitle className="text-base">Highest Priority Opportunities</CardTitle>
          <Link href="/opportunities" className="text-xs font-medium text-primary hover:underline">
            View all
          </Link>
        </CardHeader>
        <CardContent className="p-5">
          <OpportunityTable opportunities={data.highest_priority_opportunities} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex-row items-center justify-between p-5 pb-0">
          <div>
            <CardTitle className="text-base">Projects We Should Get Ahead Of</CardTitle>
            <p className="text-xs text-muted-foreground">Early signals with a high estimated likelihood of becoming a real pursuit — not yet in the pipeline.</p>
          </div>
          <Link href="/discover?category=early_signal" className="text-xs font-medium text-primary hover:underline">
            View all
          </Link>
        </CardHeader>
        <CardContent className="p-5">
          {data.high_priority_signals.length === 0 ? (
            <EmptyState title="No high-priority early signals yet" description="Sync a source on the Intelligence Sources page to start building this list." />
          ) : (
            <ul className="divide-y divide-border">
              {data.high_priority_signals.map((item) => (
                <li key={item.id} className="flex items-center justify-between gap-3 py-2.5">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium text-foreground">{item.title}</div>
                    <div className="truncate text-xs text-muted-foreground">
                      {[item.agency_name, item.location_state].filter(Boolean).join(" · ") || item.source}
                    </div>
                  </div>
                  <div className="shrink-0 text-sm font-semibold tabular-nums text-warning">{item.early_signal_score}/100</div>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="p-5 pb-0">
          <CardTitle className="text-base">What Needs Attention Today</CardTitle>
        </CardHeader>
        <CardContent className="p-5">
          {data.attention_today_tasks.length === 0 ? (
            <EmptyState title="Nothing overdue or due today" description="You're caught up on tasks." />
          ) : (
            <ul className="divide-y divide-border">
              {data.attention_today_tasks.map((task) => (
                <li key={task.id} className="flex items-center justify-between gap-3 py-2.5">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium text-foreground">{task.title}</div>
                    <div className="truncate text-xs text-muted-foreground">
                      {task.opportunity_title ?? "General"} · Due {formatDate(task.due_date)}
                    </div>
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    <PriorityBadge value={task.priority} />
                    <TaskStatusBadge value={task.status} />
                  </div>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
