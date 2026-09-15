"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  Briefcase,
  DollarSign,
  Sparkles,
  CalendarClock,
  Gavel,
  FileEdit,
  Users,
  Award,
  Trophy,
  ThumbsDown,
  Percent,
  ShieldCheck,
  Lock,
  RefreshCcw,
  Rocket,
} from "lucide-react";
import { dashboardApi } from "@/lib/api/resources";
import { KpiCard } from "@/components/dashboard/kpi-card";
import { HorizontalBarChartCard, TrendChartCard } from "@/components/dashboard/charts";
import { OpportunityTable } from "@/components/opportunities/opportunity-table";
import { TaskStatusBadge, PriorityBadge } from "@/components/domain/badges";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { LoadingState, ErrorState, EmptyState } from "@/components/ui/states";
import { formatCurrency, formatDate, cn } from "@/lib/utils";
import type { DashboardSummary } from "@/types";

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

  const { kpis } = data;
  const today = new Date();

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold text-foreground">Executive Dashboard</h1>
        <p className="text-sm text-muted-foreground">
          {today.toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric", year: "numeric" })} — Principal
          Engineering business-development pipeline health.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
        <KpiCard label="Active Opportunities" value={kpis.total_active_opportunities} icon={Briefcase} />
        <KpiCard label="Total Contract Value" value={formatCurrency(kpis.total_estimated_contract_value, { compact: true })} icon={DollarSign} />
        <KpiCard label="Est. Principal Fees" value={formatCurrency(kpis.total_estimated_fee, { compact: true })} icon={DollarSign} tone="accent" />
        <KpiCard label="Discovered This Week" value={kpis.discovered_this_week} icon={Sparkles} />
        <KpiCard label="Due Within 30 Days" value={kpis.due_within_30_days} icon={CalendarClock} tone={kpis.due_within_30_days > 0 ? "warning" : "default"} />
        <KpiCard label="Awaiting Go/No-Go" value={kpis.awaiting_go_no_go} icon={Gavel} tone={kpis.awaiting_go_no_go > 0 ? "warning" : "default"} />
        <KpiCard label="Active Proposals" value={kpis.active_proposals} icon={FileEdit} />
        <KpiCard label="Interviews Pending" value={kpis.interviews_pending} icon={Users} />
        <KpiCard label="Awards Pending" value={kpis.awards_pending} icon={Award} />
        <KpiCard label="Wins" value={kpis.wins} icon={Trophy} tone="success" />
        <KpiCard label="Losses" value={kpis.losses} icon={ThumbsDown} tone="destructive" />
        <KpiCard label="Win Rate" value={kpis.win_rate_pct !== null ? `${kpis.win_rate_pct.toFixed(0)}%` : "—"} icon={Percent} />
        <KpiCard label="SDVOSB Set-Asides" value={kpis.sdvosb_setaside_count} icon={ShieldCheck} tone="accent" />
        <KpiCard label="Limited Competition" value={kpis.sole_source_or_limited_competition_count} icon={Lock} />
        <KpiCard label="Possible Recompetes" value={kpis.recompete_count} icon={RefreshCcw} />
        <KpiCard label="Early-Stage Signals" value={kpis.early_stage_count} icon={Rocket} />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <TrendChartCard title="Pipeline Value Over Time (Est. Fee)" data={data.pipeline_value_over_time} />
        <HorizontalBarChartCard title="Pipeline by Agency" data={data.pipeline_by_agency} />
        <HorizontalBarChartCard title="Pipeline by Stage" data={data.pipeline_by_stage} />
        <HorizontalBarChartCard title="Pipeline by State" data={data.pipeline_by_state} />
        <HorizontalBarChartCard title="Pipeline by Source" data={data.pipeline_by_source} />
        <HorizontalBarChartCard title="Pipeline by NAICS Code" data={data.pipeline_by_naics} />
      </div>

      <Card>
        <CardHeader className="flex-row items-center justify-between p-4 pb-0">
          <CardTitle className="text-base">Highest Priority Opportunities</CardTitle>
          <Link href="/opportunities" className="text-xs font-medium text-primary hover:underline">
            View all
          </Link>
        </CardHeader>
        <CardContent className="p-4">
          <OpportunityTable opportunities={data.highest_priority_opportunities} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="p-4 pb-0">
          <CardTitle className="text-base">What Needs Attention Today</CardTitle>
        </CardHeader>
        <CardContent className="p-4">
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
