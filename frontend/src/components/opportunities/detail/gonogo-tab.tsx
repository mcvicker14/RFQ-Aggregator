"use client";

import { useEffect, useState } from "react";
import { gonogoApi } from "@/lib/api/resources";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { GoNoGoBadge } from "@/components/domain/badges";
import { LoadingState, ErrorState } from "@/components/ui/states";
import { useAuth } from "@/lib/auth";
import { cn, formatDateTime } from "@/lib/utils";
import type { GoNoGoReview } from "@/types";

const CAN_DECIDE_ROLES = ["administrator", "executive"];

export function GoNoGoTab({ opportunityId }: { opportunityId: string }) {
  const { user } = useAuth();
  const [review, setReview] = useState<GoNoGoReview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [scores, setScores] = useState<Record<string, number>>({});
  const [busy, setBusy] = useState(false);
  const [decisionNotes, setDecisionNotes] = useState("");

  function load() {
    setError(null);
    gonogoApi
      .get(opportunityId)
      .then((r) => {
        setReview(r);
        setScores(Object.fromEntries(r.criteria_scores.map((c) => [c.criterion, c.score])));
      })
      .catch((e) => setError(e.message));
  }

  useEffect(load, [opportunityId]); // eslint-disable-line react-hooks/exhaustive-deps

  async function saveScores() {
    if (!review) return;
    setBusy(true);
    try {
      const payload = Object.entries(scores).map(([criterion, score]) => ({ criterion, score }));
      const updated = await gonogoApi.updateCriteria(review.id, payload);
      setReview(updated);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save scores");
    } finally {
      setBusy(false);
    }
  }

  async function decide(decision: "go" | "conditional_go" | "no_go") {
    if (!review) return;
    setBusy(true);
    try {
      const updated = await gonogoApi.decide(review.id, decision, decisionNotes || undefined);
      setReview(updated);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to record decision");
    } finally {
      setBusy(false);
    }
  }

  if (error) return <ErrorState message={error} onRetry={load} />;
  if (!review) return <LoadingState />;

  const canDecide = user && CAN_DECIDE_ROLES.includes(user.role);

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
      <Card className="lg:col-span-2">
        <CardHeader>
          <CardTitle>Go/No-Go Criteria</CardTitle>
          <CardDescription>Score each criterion 1 (weak) – 5 (strong) based on what you know today.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          {review.criteria_scores.map((c) => (
            <div key={c.criterion} className="flex items-center justify-between gap-4">
              <span className="text-sm text-foreground">{c.criterion}</span>
              <div className="flex gap-1">
                {[1, 2, 3, 4, 5].map((n) => (
                  <button
                    key={n}
                    type="button"
                    onClick={() => setScores((s) => ({ ...s, [c.criterion]: n }))}
                    className={cn(
                      "flex h-7 w-7 items-center justify-center rounded-md border text-xs font-medium transition-colors",
                      scores[c.criterion] === n
                        ? "border-primary bg-primary text-primary-foreground"
                        : "border-border bg-card text-muted-foreground hover:bg-secondary"
                    )}
                  >
                    {n}
                  </button>
                ))}
              </div>
            </div>
          ))}
          <Button size="sm" className="mt-2 self-start" onClick={saveScores} disabled={busy}>
            Save Scores
          </Button>
        </CardContent>
      </Card>

      <div className="flex flex-col gap-4">
        <Card>
          <CardHeader><CardTitle>AI Recommendation Factors</CardTitle></CardHeader>
          <CardContent className="flex flex-col gap-2">
            <GoNoGoBadge value={review.ai_recommendation} />
            <p className="text-xs text-muted-foreground">{review.ai_recommendation_rationale}</p>
            <p className="text-[11px] text-muted-foreground">
              This is a recommendation only, computed from the criteria scores above. It is not a decision.
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>Leadership Decision</CardTitle></CardHeader>
          <CardContent className="flex flex-col gap-3">
            {review.decision ? (
              <>
                <GoNoGoBadge value={review.decision} />
                <p className="text-xs text-muted-foreground">
                  Recorded {formatDateTime(review.decided_at)}
                  {review.decision_notes ? ` — ${review.decision_notes}` : ""}
                </p>
              </>
            ) : canDecide ? (
              <>
                <Textarea
                  placeholder="Decision notes (optional)"
                  value={decisionNotes}
                  onChange={(e) => setDecisionNotes(e.target.value)}
                  rows={2}
                />
                <div className="flex gap-2">
                  <Button size="sm" onClick={() => decide("go")} disabled={busy}>Go</Button>
                  <Button size="sm" variant="secondary" onClick={() => decide("conditional_go")} disabled={busy}>Conditional</Button>
                  <Button size="sm" variant="destructive" onClick={() => decide("no_go")} disabled={busy}>No-Go</Button>
                </div>
              </>
            ) : (
              <p className="text-xs text-muted-foreground">
                Only an Administrator or Executive can record the final Go/No-Go decision.
              </p>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
