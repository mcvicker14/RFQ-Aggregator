"use client";

import { useState } from "react";
import Link from "next/link";
import { ChevronDown, ChevronUp, ExternalLink, MapPin, Building2, CalendarClock, Radar } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { SampleDataBadge, RelevanceTierBadge, IntelligenceCategoryBadge } from "@/components/domain/badges";
import { cn, formatDate, formatDeadline, daysUntil } from "@/lib/utils";
import type { IntelligenceItem, StatusBoardSync } from "@/types";

// Mirrors backend/app/services/intelligence_sync.py's PROMOTABLE_CATEGORIES exactly —
// only a Live Opportunity or Pre-Solicitation is ever a real pursuit to track; Early
// Signal / Award Intelligence are market intelligence by design and never become a
// pipeline entry, whether promoted automatically by sync or manually from this card.
const PROMOTABLE_CATEGORIES = new Set(["live_opportunity", "pre_solicitation"]);

const TIME_TO_PROCUREMENT_LABELS: Record<string, string> = {
  months_0_3: "0–3 months",
  months_3_6: "3–6 months",
  months_6_12: "6–12 months",
  months_12_24: "12–24 months",
  unknown: "Unknown",
};

const DETAIL_FIELDS: { key: keyof IntelligenceItem; label: string; format?: (value: string) => string }[] = [
  { key: "solicitation_number", label: "Solicitation #" },
  { key: "contract_number", label: "Contract #" },
  { key: "funding_award_number", label: "Award #" },
  { key: "project_number", label: "Project #" },
  { key: "incumbent_name", label: "Incumbent" },
  { key: "awardee_name", label: "Awardee" },
  {
    key: "estimated_time_to_procurement",
    label: "Est. Time to Procurement",
    format: (v) => TIME_TO_PROCUREMENT_LABELS[v] ?? v,
  },
  { key: "naics_code", label: "NAICS" },
  { key: "psc_code", label: "PSC" },
];

function formatMoney(value: number | null): string | null {
  if (!value) return null;
  return `$${value.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

export function IntelligenceCard({
  item,
  onTrack,
  onSyncStatusBoard,
  statusBoardSync,
}: {
  item: IntelligenceItem;
  onTrack: (item: IntelligenceItem) => Promise<void>;
  // Syncs the already-existing Opportunity to the Status Board — used both the first
  // time (item.status_board_sync is null/absent) and to retry after a failure. Never
  // creates a second Opportunity; see discover/page.tsx's handleSyncStatusBoard.
  onSyncStatusBoard?: (item: IntelligenceItem) => Promise<void>;
  // Session-local, optimistic: set the moment *this* Discover visit tracks or syncs
  // this item, before a refetch would otherwise reflect it. Overlays
  // item.status_board_sync (the server's own current state, populated by the backend
  // for every item regardless of when it was tracked) rather than replacing it — see
  // effectiveSync below. This is why an item auto-promoted or tracked in an earlier
  // session still shows its real sync state instead of looking untouched.
  statusBoardSync?: Pick<StatusBoardSync, "status" | "last_error"> | null;
}) {
  const [expanded, setExpanded] = useState(false);
  const [tracking, setTracking] = useState(false);
  const [trackError, setTrackError] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);

  const tracked = !!item.opportunity_id;
  const canTrack = !tracked && PROMOTABLE_CATEGORIES.has(item.intelligence_category);
  const effectiveSync = statusBoardSync ?? item.status_board_sync;
  const syncStatus = effectiveSync?.status;

  const rationale = item.grants_relevance_rationale ?? item.sam_relevance_rationale;
  const relevanceScore = item.grants_relevance_score ?? item.sam_relevance_score;
  const relevanceTier = item.grants_relevance_score !== null
    ? item.grants_relevance_rationale?.tier
    : item.sam_relevance_rationale?.tier;
  const relevanceLabel = item.grants_relevance_score !== null ? "Grant Relevance" : item.sam_relevance_score !== null ? "SAM Relevance" : null;

  const deadline = formatDeadline(item.proposal_due_at);
  const daysLeft = daysUntil(item.proposal_due_at);
  const isUrgent = !deadline?.expired && daysLeft !== null && daysLeft <= 14;
  const fallbackDate = item.estimated_award_date || item.posted_at;
  const fallbackLabel = item.estimated_award_date ? "Est. Award" : "Posted";
  const value = formatMoney(item.estimated_value_high ?? item.funding_amount);

  const detailFields = DETAIL_FIELDS.filter(({ key }) => !!item[key]);
  const hasExpandable = !!rationale?.why_not_fit || detailFields.length > 0 || (item.relevant_disciplines?.length ?? 0) > 0;

  async function handleTrack() {
    setTracking(true);
    setTrackError(null);
    try {
      await onTrack(item);
    } catch (e) {
      setTrackError(e instanceof Error ? e.message : "Failed to track — try again");
    } finally {
      setTracking(false);
    }
  }

  async function handleSyncStatusBoard() {
    if (!onSyncStatusBoard) return;
    setSyncing(true);
    try {
      await onSyncStatusBoard(item);
    } finally {
      setSyncing(false);
    }
  }

  return (
    <Card className="flex flex-col gap-2.5 p-4 transition-shadow hover:shadow-md">
      <div className="flex items-start justify-between gap-2">
        <IntelligenceCategoryBadge value={item.intelligence_category} />
        {item.is_sample_data && <SampleDataBadge />}
      </div>

      <div>
        <h3 className="text-sm font-semibold leading-snug text-foreground">{item.title}</h3>
        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-muted-foreground">
          {item.agency_name && (
            <span className="flex items-center gap-1"><Building2 className="h-3 w-3" /> {item.agency_name}</span>
          )}
          {(item.location_city || item.location_state) && (
            <span className="flex items-center gap-1">
              <MapPin className="h-3 w-3" /> {[item.location_city, item.location_state].filter(Boolean).join(", ")}
            </span>
          )}
          <span className="flex items-center gap-1"><Radar className="h-3 w-3" /> {item.source}</span>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-4">
        {relevanceLabel && relevanceScore !== null && (
          <div className="flex flex-col gap-1">
            <span className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">{relevanceLabel}</span>
            <RelevanceTierBadge tier={relevanceTier ?? "unscored"} score={relevanceScore} />
          </div>
        )}
        {item.early_signal_score !== null && (
          <div className="flex flex-col gap-1">
            <span className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">Signal Score</span>
            <span className="text-sm font-semibold tabular-nums text-foreground">{item.early_signal_score}/100</span>
          </div>
        )}
        {value && (
          <div className="flex flex-col gap-1">
            <span className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
              {item.funding_amount ? "Funding" : "Est. Value"}
            </span>
            <span className="text-sm font-semibold tabular-nums text-foreground">{value}</span>
          </div>
        )}
      </div>

      {deadline ? (
        <div className={cn("flex items-center gap-1.5 text-xs", isUrgent ? "font-semibold text-destructive" : "text-muted-foreground")}>
          <CalendarClock className="h-3.5 w-3.5" />
          {deadline.text}
        </div>
      ) : fallbackDate ? (
        <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <CalendarClock className="h-3.5 w-3.5" />
          {fallbackLabel} {formatDate(fallbackDate)}
        </div>
      ) : null}

      {rationale?.why_relevant && (
        <div className="rounded-md bg-secondary/40 px-2.5 py-2 text-xs leading-relaxed text-foreground">
          <span className="font-medium">Why it fits: </span>
          {rationale.why_relevant}
        </div>
      )}

      {expanded && (
        <div className="flex flex-col gap-2 border-t border-border pt-2.5">
          {rationale?.why_not_fit && (
            <div className="text-xs leading-relaxed text-muted-foreground">
              <span className="font-medium text-foreground">Why it may not fit: </span>
              {rationale.why_not_fit}
            </div>
          )}
          {(item.relevant_disciplines?.length ?? 0) > 0 && (
            <div className="flex flex-wrap items-center gap-1.5 text-xs">
              <span className="font-medium text-foreground">Disciplines:</span>
              {item.relevant_disciplines!.map((d) => (
                <Badge key={d} variant="outline" className="font-normal">{d}</Badge>
              ))}
            </div>
          )}
          {detailFields.length > 0 && (
            <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-3">
              {detailFields.map(({ key, label, format }) => (
                <div key={key}>
                  <dt className="text-muted-foreground">{label}</dt>
                  <dd className="truncate font-medium text-foreground">
                    {format ? format(String(item[key])) : String(item[key])}
                  </dd>
                </div>
              ))}
            </dl>
          )}
        </div>
      )}

      {hasExpandable && (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="flex w-fit items-center gap-1 text-xs font-medium text-primary hover:underline"
        >
          {expanded ? <>Show less <ChevronUp className="h-3 w-3" /></> : <>Show more <ChevronDown className="h-3 w-3" /></>}
        </button>
      )}

      <div className="mt-auto flex items-center justify-between gap-2 pt-1.5">
        {!tracked ? (
          canTrack ? (
            <Button size="sm" onClick={handleTrack} disabled={tracking}>
              {tracking ? "Tracking…" : "Track + Add to Status Board"}
            </Button>
          ) : (
            <Button size="sm" variant="outline" onClick={() => setExpanded(true)}>
              View Intelligence
            </Button>
          )
        ) : syncStatus === "synced" ? (
          // A status, not an action — "Tracked in app" and "On Status Board" are two
          // separate facts, and this item already has both, so one pill covers it.
          <Link
            href={`/opportunities/${item.opportunity_id}`}
            className="inline-flex items-center gap-1 rounded-md bg-success/10 px-2.5 py-1.5 text-xs font-semibold text-success transition-colors hover:bg-success/15"
          >
            ✓ On Status Board
          </Link>
        ) : syncStatus === "failed" ? (
          <div className="flex items-center gap-1.5">
            <span className="inline-flex items-center gap-1 rounded-md bg-warning/10 px-2.5 py-1.5 text-xs font-semibold text-warning">
              ⚠ Status Board sync failed
            </span>
            <Button size="sm" variant="outline" onClick={handleSyncStatusBoard} disabled={syncing}>
              {syncing ? "Retrying…" : "Retry Status Board"}
            </Button>
          </div>
        ) : (
          // Tracked (often auto-promoted, never touched by this card before) but
          // never synced — Tracked-in-app and Add-to-Status-Board are shown together,
          // never collapsed into one, per the two being separate states.
          <div className="flex items-center gap-1.5">
            <Link
              href={`/opportunities/${item.opportunity_id}`}
              className="text-xs font-medium text-muted-foreground hover:text-foreground hover:underline"
            >
              Tracked in app
            </Link>
            <Button size="sm" onClick={handleSyncStatusBoard} disabled={syncing}>
              {syncing ? "Syncing…" : "Add to Status Board"}
            </Button>
          </div>
        )}
        {item.source_url && (
          <a
            href={item.source_url}
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-1 text-xs text-muted-foreground hover:text-primary"
          >
            Open Source <ExternalLink className="h-3 w-3" />
          </a>
        )}
      </div>
      {trackError && <p className="text-xs text-destructive">{trackError}</p>}
      {syncStatus === "failed" && effectiveSync?.last_error && (
        <p className="text-xs text-warning">{effectiveSync.last_error}</p>
      )}
    </Card>
  );
}
