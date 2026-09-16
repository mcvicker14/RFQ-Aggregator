"use client";

import { useEffect, useMemo, useState } from "react";
import { RefreshCcw, PlayCircle, History } from "lucide-react";
import { intelligenceApi } from "@/lib/api/resources";
import { useAuth } from "@/lib/auth";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { LoadingState, ErrorState } from "@/components/ui/states";
import { titleCase } from "@/lib/utils";
import type { IntelligenceSource, IntelligenceSyncRun, JurisdictionLevel, SourceHealthStatus, SyncRunStatus } from "@/types";

const HEALTH_BADGE: Record<SourceHealthStatus, { variant: "success" | "warning" | "destructive" | "muted" | "outline"; label: string }> = {
  healthy: { variant: "success", label: "Healthy" },
  degraded: { variant: "warning", label: "Degraded" },
  failing: { variant: "destructive", label: "Failing" },
  needs_configuration: { variant: "warning", label: "Needs Configuration" },
  manual_only: { variant: "outline", label: "Manual Only" },
  never_run: { variant: "muted", label: "Never Run" },
};

const SYNC_RUN_STATUS_BADGE: Record<SyncRunStatus, { variant: "success" | "warning" | "destructive" | "muted" | "outline"; label: string }> = {
  running: { variant: "outline", label: "Running" },
  success: { variant: "success", label: "Success" },
  partial_failure: { variant: "warning", label: "Partial Failure" },
  failure: { variant: "destructive", label: "Failure" },
};

const CATEGORY_LABEL: Record<string, string> = {
  live_opportunity: "Live Opportunity",
  pre_solicitation: "Pre-Solicitation",
  early_signal: "Early Signal",
  award_intelligence: "Award Intelligence",
};

const JURISDICTIONS: JurisdictionLevel[] = ["federal", "state", "local", "regional", "private"];

function formatDate(value: string | null): string {
  if (!value) return "Never";
  return new Date(value).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export default function IntelligenceSourcesPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "administrator";
  const canSync = user ? ["business_development", "executive", "administrator"].includes(user.role) : false;

  const [sources, setSources] = useState<IntelligenceSource[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [jurisdiction, setJurisdiction] = useState("");
  const [syncingId, setSyncingId] = useState<string | null>(null);
  const [syncingAll, setSyncingAll] = useState(false);
  const [syncAllMessage, setSyncAllMessage] = useState<string | null>(null);

  const [historySource, setHistorySource] = useState<IntelligenceSource | null>(null);
  const [syncRuns, setSyncRuns] = useState<IntelligenceSyncRun[] | null>(null);
  const [syncRunsError, setSyncRunsError] = useState<string | null>(null);

  function load() {
    setError(null);
    intelligenceApi.listSources().then(setSources).catch((e) => setError(e.message));
  }
  useEffect(load, []);

  async function syncOne(id: string) {
    setSyncingId(id);
    try {
      await intelligenceApi.syncSource(id);
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Sync failed");
    } finally {
      setSyncingId(null);
    }
  }

  async function syncAll() {
    setSyncingAll(true);
    setSyncAllMessage(null);
    try {
      const result = await intelligenceApi.syncAll();
      setSyncAllMessage(
        `${result.sources_succeeded} of ${result.sources_attempted} source(s) synced successfully.` +
          (result.sources_skipped.length ? ` Skipped: ${result.sources_skipped.join("; ")}` : "")
      );
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Sync all failed");
    } finally {
      setSyncingAll(false);
    }
  }

  async function toggleEnabled(source: IntelligenceSource) {
    await intelligenceApi.updateSource(source.id, { is_enabled: !source.is_enabled });
    load();
  }

  function openHistory(source: IntelligenceSource) {
    setHistorySource(source);
    setSyncRuns(null);
    setSyncRunsError(null);
    intelligenceApi
      .syncRuns(source.id, 20)
      .then(setSyncRuns)
      .catch((e) => setSyncRunsError(e instanceof Error ? e.message : "Failed to load sync history"));
  }

  const filtered = useMemo(() => {
    if (!sources) return null;
    return sources.filter((s) => {
      if (jurisdiction && s.jurisdiction_level !== jurisdiction) return false;
      if (q) {
        const text = `${s.name} ${s.organization ?? ""} ${s.geographic_coverage ?? ""}`.toLowerCase();
        if (!text.includes(q.toLowerCase())) return false;
      }
      return true;
    });
  }, [sources, q, jurisdiction]);

  if (error) return <ErrorState message={error} onRetry={load} />;
  if (!sources || !filtered) return <LoadingState />;

  const enabledCount = sources.filter((s) => s.is_enabled).length;
  const workingCount = sources.filter((s) => s.connector_key).length;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-foreground">Intelligence Sources</h1>
          <p className="text-sm text-muted-foreground">
            The Source Registry — every public source Phase 2 tracks, whether or not it's automated yet.{" "}
            {workingCount} of {sources.length} have a working connector; {enabledCount} enabled.
          </p>
        </div>
        {canSync && (
          <Button onClick={syncAll} disabled={syncingAll}>
            <PlayCircle className={syncingAll ? "h-4 w-4 animate-pulse" : "h-4 w-4"} />
            {syncingAll ? "Syncing all…" : "Sync All Enabled Sources"}
          </Button>
        )}
      </div>

      {syncAllMessage && (
        <div className="rounded-md border border-border bg-secondary/40 p-3 text-sm text-foreground">{syncAllMessage}</div>
      )}

      <div className="flex flex-wrap gap-2">
        <Input placeholder="Search sources…" value={q} onChange={(e) => setQ(e.target.value)} className="max-w-xs" />
        <Select value={jurisdiction || "all"} onValueChange={(v) => setJurisdiction(v === "all" ? "" : v)}>
          <SelectTrigger className="w-44"><SelectValue placeholder="Jurisdiction" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All jurisdictions</SelectItem>
            {JURISDICTIONS.map((j) => <SelectItem key={j} value={j}>{titleCase(j)}</SelectItem>)}
          </SelectContent>
        </Select>
      </div>

      <Card>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Source</TableHead>
              <TableHead>Coverage</TableHead>
              <TableHead>Category</TableHead>
              <TableHead>Health</TableHead>
              <TableHead>Last Sync</TableHead>
              {isAdmin && <TableHead>Enabled</TableHead>}
              {canSync && <TableHead>Action</TableHead>}
            </TableRow>
          </TableHeader>
          <TableBody>
            {filtered.map((s) => {
              const health = HEALTH_BADGE[s.health_status];
              return (
                <TableRow key={s.id}>
                  <TableCell>
                    <div className="font-medium text-foreground">{s.name}</div>
                    <div className="text-xs text-muted-foreground">{s.organization ?? "—"}</div>
                    {s.last_error && (
                      <button
                        onClick={() => openHistory(s)}
                        className="mt-0.5 block max-w-xs truncate text-left text-xs text-destructive underline decoration-dotted underline-offset-2 hover:text-destructive/80"
                        title={`${s.last_error} — click to view sync history`}
                      >
                        {s.last_error}
                      </button>
                    )}
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {titleCase(s.jurisdiction_level)}
                    {s.geographic_coverage && <div>{s.geographic_coverage}</div>}
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {s.default_intelligence_category ? CATEGORY_LABEL[s.default_intelligence_category] : "—"}
                  </TableCell>
                  <TableCell><Badge variant={health.variant}>{health.label}</Badge></TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {formatDate(s.last_successful_sync_at)}
                    {s.last_result_count !== null && <div>{s.last_result_count} item(s)</div>}
                    {s.connector_key && (
                      <button
                        onClick={() => openHistory(s)}
                        className="mt-0.5 flex items-center gap-1 text-xs text-muted-foreground underline decoration-dotted underline-offset-2 hover:text-foreground"
                      >
                        <History className="h-3 w-3" /> History
                      </button>
                    )}
                  </TableCell>
                  {isAdmin && (
                    <TableCell>
                      <button
                        onClick={() => toggleEnabled(s)}
                        className={
                          "rounded-full px-2.5 py-1 text-xs font-medium transition-colors " +
                          (s.is_enabled ? "bg-success/15 text-success" : "bg-muted text-muted-foreground")
                        }
                      >
                        {s.is_enabled ? "Enabled" : "Disabled"}
                      </button>
                    </TableCell>
                  )}
                  {canSync && (
                    <TableCell>
                      {s.connector_key ? (
                        <Button size="sm" variant="outline" onClick={() => syncOne(s.id)} disabled={syncingId === s.id}>
                          <RefreshCcw className={syncingId === s.id ? "h-3.5 w-3.5 animate-spin" : "h-3.5 w-3.5"} />
                          {syncingId === s.id ? "Syncing…" : "Sync Now"}
                        </Button>
                      ) : (
                        <span className="text-xs text-muted-foreground">No connector yet</span>
                      )}
                    </TableCell>
                  )}
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </Card>

      <Dialog open={historySource !== null} onOpenChange={(open) => { if (!open) setHistorySource(null); }}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Sync History — {historySource?.name}</DialogTitle>
            <DialogDescription>
              The most recent sync runs for this source, including the full error for any that failed —
              no need to check Render logs.
            </DialogDescription>
          </DialogHeader>
          {syncRunsError && (
            <ErrorState message={syncRunsError} onRetry={() => historySource && openHistory(historySource)} />
          )}
          {!syncRunsError && syncRuns === null && <LoadingState />}
          {!syncRunsError && syncRuns !== null && syncRuns.length === 0 && (
            <p className="text-sm text-muted-foreground">No sync runs recorded yet for this source.</p>
          )}
          {!syncRunsError && syncRuns !== null && syncRuns.length > 0 && (
            <div className="flex flex-col gap-3">
              {syncRuns.map((run) => {
                const statusBadge = SYNC_RUN_STATUS_BADGE[run.status];
                return (
                  <div key={run.id} className="rounded-md border border-border p-3 text-sm">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="font-medium text-foreground">{formatDate(run.started_at)}</div>
                      <div className="flex items-center gap-2">
                        <Badge variant="outline">{titleCase(run.triggered_by)}</Badge>
                        <Badge variant={statusBadge.variant}>{statusBadge.label}</Badge>
                      </div>
                    </div>
                    <div className="mt-1.5 text-xs text-muted-foreground">
                      Fetched {run.items_fetched} · Created {run.items_created} · Updated {run.items_updated} ·
                      Unchanged {run.items_unchanged} · Errored {run.items_errored}
                    </div>
                    {run.error_detail && (
                      <pre className="mt-2 max-h-40 overflow-y-auto whitespace-pre-wrap break-words rounded bg-secondary/40 p-2 text-xs text-destructive">
                        {run.error_detail}
                      </pre>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
