"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Columns3, Table2 } from "lucide-react";
import { opportunitiesApi, pipelineStagesApi } from "@/lib/api/resources";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ScoreBadge, SampleDataBadge } from "@/components/domain/badges";
import { OpportunityTable } from "@/components/opportunities/opportunity-table";
import { NewOpportunityDialog } from "@/components/opportunities/new-opportunity-dialog";
import { LoadingState, ErrorState } from "@/components/ui/states";
import { cn, formatCurrency, formatDate } from "@/lib/utils";
import type { OpportunityListItem, PipelineStage } from "@/types";

export default function PipelinePage() {
  const [stages, setStages] = useState<PipelineStage[]>([]);
  const [opportunities, setOpportunities] = useState<OpportunityListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<"kanban" | "table">("kanban");
  const router = useRouter();

  function load() {
    setError(null);
    Promise.all([pipelineStagesApi.list(), opportunitiesApi.list({ limit: 500 })])
      .then(([s, o]) => {
        setStages(s.filter((stage) => stage.is_active).sort((a, b) => a.sort_order - b.sort_order));
        setOpportunities(o);
      })
      .catch((e) => setError(e.message));
  }
  useEffect(load, []);

  const byStage = useMemo(() => {
    const map = new Map<string, OpportunityListItem[]>();
    (opportunities ?? []).forEach((o) => {
      const key = o.pipeline_stage_id ?? "none";
      map.set(key, [...(map.get(key) ?? []), o]);
    });
    return map;
  }, [opportunities]);

  async function moveStage(opportunityId: string, stageId: string) {
    setOpportunities((prev) =>
      prev ? prev.map((o) => (o.id === opportunityId ? { ...o, pipeline_stage_id: stageId } : o)) : prev
    );
    await opportunitiesApi.changeStage(opportunityId, stageId);
  }

  if (error) return <ErrorState message={error} onRetry={load} />;
  if (!opportunities) return <LoadingState label="Loading pipeline…" />;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-foreground">Pipeline</h1>
          <p className="text-sm text-muted-foreground">{opportunities.length} active opportunities across {stages.length} stages.</p>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex rounded-md border border-border p-0.5">
            <Button variant={view === "kanban" ? "secondary" : "ghost"} size="sm" onClick={() => setView("kanban")}>
              <Columns3 className="h-3.5 w-3.5" /> Board
            </Button>
            <Button variant={view === "table" ? "secondary" : "ghost"} size="sm" onClick={() => setView("table")}>
              <Table2 className="h-3.5 w-3.5" /> Table
            </Button>
          </div>
          <NewOpportunityDialog />
        </div>
      </div>

      {view === "table" ? (
        <Card><OpportunityTable opportunities={opportunities} /></Card>
      ) : (
        <div className="flex gap-3 overflow-x-auto pb-4">
          {stages.map((stage) => {
            const items = byStage.get(stage.id) ?? [];
            const stageValue = items.reduce((sum, o) => sum + (o.estimated_fee ?? 0), 0);
            return (
              <div key={stage.id} className="flex w-72 shrink-0 flex-col rounded-lg border border-border bg-secondary/40">
                <div className="flex items-center justify-between rounded-t-lg border-b border-border bg-card px-3 py-2.5">
                  <span className="text-xs font-semibold text-foreground">{stage.name}</span>
                  <span className="rounded-full bg-secondary px-1.5 py-0.5 text-[10.5px] font-medium tabular-nums text-muted-foreground">
                    {items.length} · {formatCurrency(stageValue, { compact: true })}
                  </span>
                </div>
                <div className="flex flex-col gap-2 p-2">
                  {items.map((opp) => (
                    <Card
                      key={opp.id}
                      className="cursor-pointer p-3 transition-shadow hover:border-primary/30 hover:shadow-md"
                      onClick={() => router.push(`/opportunities/${opp.id}`)}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <span className="text-xs font-medium leading-snug text-foreground line-clamp-2">{opp.title}</span>
                        <ScoreBadge score={opp.current_score} band={opp.current_score_band} />
                      </div>
                      <div className="mt-1.5 flex items-center justify-between text-[11px] text-muted-foreground">
                        <span>{opp.agency?.short_name ?? "—"}</span>
                        <span className="font-medium tabular-nums">{formatCurrency(opp.estimated_fee, { compact: true })}</span>
                      </div>
                      <div className="mt-1 flex items-center justify-between gap-2">
                        <span className={cn("text-[11px]", opp.is_sample_data && "opacity-80")}>{formatDate(opp.proposal_due_at)}</span>
                        {opp.is_sample_data && <SampleDataBadge className="text-[9px]" />}
                      </div>
                      <div onClick={(e) => e.stopPropagation()} className="mt-2">
                        <Select value={stage.id} onValueChange={(v) => moveStage(opp.id, v)}>
                          <SelectTrigger className="h-7 text-[11px]"><SelectValue /></SelectTrigger>
                          <SelectContent>
                            {stages.map((s) => <SelectItem key={s.id} value={s.id}>{s.name}</SelectItem>)}
                          </SelectContent>
                        </Select>
                      </div>
                    </Card>
                  ))}
                  {items.length === 0 && (
                    <div className="rounded-md border border-dashed border-border py-6 text-center text-[11px] text-muted-foreground">
                      No opportunities
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
