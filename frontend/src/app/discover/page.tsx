"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { AlertTriangle, CheckCircle2, RefreshCcw } from "lucide-react";
import { ingestionApi } from "@/lib/api/resources";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { LoadingState } from "@/components/ui/states";

export default function DiscoverPage() {
  const [status, setStatus] = useState<{ connector: string; configured: boolean; detail: string | null } | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [result, setResult] = useState<{ created: number; updated: number; unchanged: number; total_fetched: number } | null>(null);
  const [error, setError] = useState<string | null>(null);

  function loadStatus() {
    ingestionApi.samGovStatus().then(setStatus).catch(() => setStatus(null));
  }
  useEffect(loadStatus, []);

  async function sync() {
    setSyncing(true);
    setError(null);
    setResult(null);
    try {
      const r = await ingestionApi.samGovSync(30);
      setResult(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Sync failed");
    } finally {
      setSyncing(false);
    }
  }

  if (!status) return <LoadingState />;

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold text-foreground">Discover</h1>
        <p className="text-sm text-muted-foreground">Pull new opportunities from connected external sources.</p>
      </div>

      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <div>
            <CardTitle>SAM.gov Opportunities</CardTitle>
            <CardDescription>Solicitations, presolicitations, and sources sought from the public SAM.gov API.</CardDescription>
          </div>
          {status.configured ? (
            <span className="flex items-center gap-1.5 text-xs font-medium text-success"><CheckCircle2 className="h-4 w-4" /> Configured</span>
          ) : (
            <span className="flex items-center gap-1.5 text-xs font-medium text-warning"><AlertTriangle className="h-4 w-4" /> Not Configured</span>
          )}
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          {!status.configured && (
            <div className="rounded-md bg-warning/10 p-3 text-sm text-foreground">
              {status.detail}
            </div>
          )}
          <Button onClick={sync} disabled={!status.configured || syncing} className="self-start">
            <RefreshCcw className={syncing ? "h-4 w-4 animate-spin" : "h-4 w-4"} /> {syncing ? "Syncing…" : "Sync Now (last 30 days)"}
          </Button>
          {error && <p className="text-xs text-destructive">{error}</p>}
          {result && (
            <div className="rounded-md border border-border bg-secondary/40 p-3 text-sm text-foreground">
              Fetched {result.total_fetched} notices — {result.created} new, {result.updated} updated, {result.unchanged} unchanged.
              {" "}
              <Link href="/opportunities" className="font-medium text-primary hover:underline">View opportunities</Link>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Other Sources (Planned)</CardTitle>
          <CardDescription>
            USASpending/FPDS, state and municipal procurement portals, agency forecasts, and grant announcements are
            planned for a later phase (see docs/ROADMAP.md). Each will plug into the same connector framework as
            SAM.gov above.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            In the meantime, use <Link href="/opportunities" className="font-medium text-primary hover:underline">New Opportunity</Link> to
            add anything you find manually — a referral, an agency forecast, or an industry-day conversation.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
