"use client";

import { useEffect, useState } from "react";
import { RefreshCcw } from "lucide-react";
import { opportunitiesApi } from "@/lib/api/resources";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ScoreBadge } from "@/components/domain/badges";
import { LoadingState, ErrorState } from "@/components/ui/states";
import { cn, titleCase } from "@/lib/utils";
import type { Opportunity, OpportunityScore } from "@/types";

const CATEGORY_LABELS: Record<string, string> = {
  strategic_fit: "Strategic Fit",
  customer_fit: "Customer Fit",
  contract_fit: "Contract Fit",
  geographic_fit: "Geographic Fit",
  competitive_advantage: "Competitive Advantage",
  financial_attractiveness: "Financial Attractiveness",
  competition: "Competition",
  timing: "Timing",
};

export function ScoreTab({ opportunity, onRescored }: { opportunity: Opportunity; onRescored: () => void }) {
  const [score, setScore] = useState<OpportunityScore | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function load() {
    setError(null);
    opportunitiesApi.getScore(opportunity.id).then(setScore).catch((e) => setError(e.message));
  }

  useEffect(load, [opportunity.id]); // eslint-disable-line react-hooks/exhaustive-deps

  async function recalculate() {
    setBusy(true);
    try {
      const updated = await opportunitiesApi.recalculateScore(opportunity.id);
      setScore(updated);
      onRescored();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to recalculate score");
    } finally {
      setBusy(false);
    }
  }

  if (error) return <ErrorState message={error} onRetry={load} />;
  if (!score) return <LoadingState />;

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
      <Card className="lg:col-span-2">
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle>Principal Pursuit Score</CardTitle>
          <Button variant="outline" size="sm" onClick={recalculate} disabled={busy}>
            <RefreshCcw className={cn("h-3.5 w-3.5", busy && "animate-spin")} /> Recalculate
          </Button>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="flex items-center gap-3">
            <ScoreBadge score={score.score} band={score.band} size="lg" />
            <span className="text-sm text-muted-foreground">{titleCase(score.band)} priority</span>
          </div>

          <div className="flex flex-col gap-3">
            {Object.entries(score.category_scores).map(([key, value]) => (
              <div key={key}>
                <div className="mb-1 flex items-center justify-between text-xs">
                  <span className="font-medium text-foreground">{CATEGORY_LABELS[key] ?? titleCase(key)}</span>
                  <span className="tabular-nums text-muted-foreground">{value}/100</span>
                </div>
                <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
                  <div
                    className={cn("h-full rounded-full", value >= 75 ? "bg-success" : value >= 50 ? "bg-warning" : "bg-destructive")}
                    style={{ width: `${value}%` }}
                  />
                </div>
                {score.category_rationale[key]?.length > 0 && (
                  <ul className="mt-1 list-disc pl-4 text-xs text-muted-foreground">
                    {score.category_rationale[key].map((b, i) => <li key={i}>{b}</li>)}
                  </ul>
                )}
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      <div className="flex flex-col gap-4">
        <Card>
          <CardHeader><CardTitle>Why This Scores Highly</CardTitle></CardHeader>
          <CardContent><p className="text-sm text-foreground">{score.why_it_scores_highly}</p></CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Primary Concern</CardTitle></CardHeader>
          <CardContent><p className="text-sm text-foreground">{score.primary_concern}</p></CardContent>
        </Card>
        <p className="px-1 text-xs text-muted-foreground">
          This score is a decision aid, not a decision — it is deterministic and rule-based (see
          docs/SCORING_METHODOLOGY.md), not AI-generated. It feeds the Go/No-Go tool&apos;s recommendation, but
          Principal leadership always records the actual pursuit decision.
        </p>
      </div>
    </div>
  );
}
