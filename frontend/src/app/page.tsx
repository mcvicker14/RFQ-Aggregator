"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { dashboardApi } from "@/lib/api/resources";
import { DashboardDetails } from "@/components/dashboard/dashboard-details";
import { StatusBoardWorkspace } from "@/components/status-board/status-board-workspace";
import { formatDate } from "@/lib/utils";
import type { DashboardSummary } from "@/types";

export default function HomePage() {
  const [data, setData] = useState<DashboardSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  function load() { dashboardApi.summary().then(setData).catch(e => setError(e.message)); }
  useEffect(load, []);
  return <div className="min-w-0 space-y-8">
    <StatusBoardWorkspace />
    <section className="border-t border-border pt-5" aria-labelledby="attention-heading">
      <div className="mb-3 flex items-center justify-between"><h2 id="attention-heading" className="text-sm font-semibold">Needs attention</h2><Link href="/tasks" className="text-xs text-primary hover:underline">All tasks</Link></div>
      {data ? <>
        <ul className="divide-y divide-border">{data.attention_today_tasks.slice(0, 3).map(task => <li key={task.id} className="flex items-center justify-between gap-3 py-2 text-sm"><Link href="/tasks" className="min-w-0 truncate hover:underline">{task.title}</Link><span className="shrink-0 text-xs text-muted-foreground">Due {formatDate(task.due_date)}</span></li>)}</ul>
        {!data.attention_today_tasks.length && <p className="text-sm text-muted-foreground">No tasks overdue or due today.</p>}
        <div className="mt-3 flex flex-wrap gap-x-5 gap-y-2 text-xs"><Link href={`/opportunities?kpi=awaiting_go_no_go${data.include_samples ? "" : "&include_sample_data=false"}`} className="text-primary hover:underline">{data.kpis.awaiting_go_no_go} awaiting Go/No-Go</Link><Link href="/sources?health=error" className="text-primary hover:underline">{data.intelligence.sources_with_errors} sources need review</Link></div>
      </> : <p className="text-sm text-muted-foreground">{error || "Loading attention items…"}</p>}
    </section>
    <details className="border-t border-border pt-5"><summary className="cursor-pointer text-sm font-semibold">Pipeline overview, intelligence and reports</summary>
      <p className="mt-2 text-xs text-muted-foreground">All dashboard metrics, charts, priority opportunities and early signals.</p>
      {data ? <DashboardDetails data={data} /> : <button className="mt-3 text-sm text-primary" onClick={load}>Retry dashboard</button>}
    </details>
  </div>;
}
