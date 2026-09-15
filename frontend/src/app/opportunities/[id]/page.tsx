"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams } from "next/navigation";
import { opportunitiesApi, pipelineStagesApi } from "@/lib/api/resources";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { LoadingState, ErrorState } from "@/components/ui/states";
import { ScoreBadge, SampleDataBadge, SetAsideBadge, MaturityBadge } from "@/components/domain/badges";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { formatCurrency } from "@/lib/utils";
import type { Opportunity, PipelineStage } from "@/types";
import { OverviewTab } from "@/components/opportunities/detail/overview-tab";
import { ScoreTab } from "@/components/opportunities/detail/score-tab";
import { GoNoGoTab } from "@/components/opportunities/detail/gonogo-tab";
import { TasksTab } from "@/components/opportunities/detail/tasks-tab";
import { TeamTab } from "@/components/opportunities/detail/team-tab";
import { DocumentsTab } from "@/components/opportunities/detail/documents-tab";
import { ForecastTab } from "@/components/opportunities/detail/forecast-tab";
import { TimelineTab } from "@/components/opportunities/detail/timeline-tab";

export default function OpportunityDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [opp, setOpp] = useState<Opportunity | null>(null);
  const [stages, setStages] = useState<PipelineStage[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [stageBusy, setStageBusy] = useState(false);

  const load = useCallback(() => {
    setError(null);
    opportunitiesApi.get(id).then(setOpp).catch((e) => setError(e.message));
  }, [id]);

  useEffect(load, [load]);
  useEffect(() => {
    pipelineStagesApi.list().then(setStages).catch(() => setStages([]));
  }, []);

  if (error) return <ErrorState message={error} onRetry={load} />;
  if (!opp) return <LoadingState label="Loading opportunity…" />;

  async function handleStageChange(stageId: string) {
    setStageBusy(true);
    try {
      const updated = await opportunitiesApi.changeStage(opp!.id, stageId);
      setOpp(updated);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to change stage");
    } finally {
      setStageBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-xl font-semibold text-foreground">{opp.title}</h1>
            {opp.is_sample_data && <SampleDataBadge />}
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted-foreground">
            <span>{opp.agency?.name ?? "No agency on file"}</span>
            {opp.solicitation_number && <span>· {opp.solicitation_number}</span>}
            {opp.location_state && <span>· {opp.location_city ? `${opp.location_city}, ` : ""}{opp.location_state}</span>}
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <ScoreBadge score={opp.current_score} band={opp.current_score_band} />
            <SetAsideBadge value={opp.set_aside} />
            <MaturityBadge value={opp.maturity_stage} />
            {opp.estimated_fee && (
              <span className="text-xs text-muted-foreground">Est. fee {formatCurrency(opp.estimated_fee, { compact: true })}</span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">Stage</span>
          <Select value={opp.pipeline_stage_id ?? undefined} onValueChange={handleStageChange} disabled={stageBusy}>
            <SelectTrigger className="w-56"><SelectValue placeholder="Set stage" /></SelectTrigger>
            <SelectContent>
              {stages.map((s) => <SelectItem key={s.id} value={s.id}>{s.name}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
      </div>

      <Tabs defaultValue="overview">
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="score">Score</TabsTrigger>
          <TabsTrigger value="gonogo">Go/No-Go</TabsTrigger>
          <TabsTrigger value="tasks">Tasks</TabsTrigger>
          <TabsTrigger value="team">Team &amp; Contacts</TabsTrigger>
          <TabsTrigger value="documents">Documents</TabsTrigger>
          <TabsTrigger value="forecast">Forecast</TabsTrigger>
          <TabsTrigger value="timeline">Timeline</TabsTrigger>
        </TabsList>

        <TabsContent value="overview"><OverviewTab opportunity={opp} onUpdated={setOpp} /></TabsContent>
        <TabsContent value="score"><ScoreTab opportunity={opp} onRescored={load} /></TabsContent>
        <TabsContent value="gonogo"><GoNoGoTab opportunityId={opp.id} /></TabsContent>
        <TabsContent value="tasks"><TasksTab opportunityId={opp.id} /></TabsContent>
        <TabsContent value="team"><TeamTab opportunityId={opp.id} /></TabsContent>
        <TabsContent value="documents"><DocumentsTab opportunityId={opp.id} /></TabsContent>
        <TabsContent value="forecast"><ForecastTab opportunity={opp} /></TabsContent>
        <TabsContent value="timeline"><TimelineTab opportunityId={opp.id} /></TabsContent>
      </Tabs>
    </div>
  );
}
