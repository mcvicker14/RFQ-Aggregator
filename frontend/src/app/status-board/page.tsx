"use client";

import { useEffect, useState, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { RefreshCw, ExternalLink } from "lucide-react";
import { statusBoardApi } from "@/lib/api/resources";
import { StatusBoardTable } from "@/components/status-board/status-board-table";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { LoadingState, ErrorState } from "@/components/ui/states";
import { FilterChip } from "@/components/ui/filter-chip";
import { formatDateTime } from "@/lib/utils";
import { cn } from "@/lib/utils";
import type { StatusBoardFilterName, StatusBoardListResponse, StatusBoardSortField } from "@/types";

// Mirrors the Dashboard's own count labels — see backend/app/services/
// status_board_filters.py's STATUS_BOARD_FILTER_NAMES for the exact accepted values.
const FILTER_LABELS: Record<StatusBoardFilterName, string> = {
  all_active: "All Active",
  submit_y: "Submit = Y",
  submit_n_blank: "Submit = N / Blank",
  submitted: "Submitted",
  not_submitted: "Not Submitted",
  due_soon: "Due Soon",
  past_due: "Past Due",
};

const SORT_LABELS: Record<StatusBoardSortField, string> = {
  due_date: "Sort: Due Date",
  date_added: "Sort: Date Added",
  client: "Sort: Client",
  submit_status: "Sort: Submit Status",
  importance: "Sort: Importance",
  probability: "Sort: Probability",
};

function StatusBoardPageInner() {
  const searchParams = useSearchParams();
  const [data, setData] = useState<StatusBoardListResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const [filter, setFilter] = useState<StatusBoardFilterName>(
    (searchParams.get("filter") as StatusBoardFilterName) || "all_active"
  );
  const [client, setClient] = useState("");
  const [sort, setSort] = useState<StatusBoardSortField>("due_date");
  const [order, setOrder] = useState<"asc" | "desc">("asc");
  const cameFromDashboard = searchParams.get("filter") !== null;

  function load() {
    setError(null);
    statusBoardApi
      .list({ filter, client: client || undefined, sort, order })
      .then(setData)
      .catch((e) => setError(e.message));
  }

  useEffect(load, [filter, client, sort, order]); // eslint-disable-line react-hooks/exhaustive-deps

  async function handleRefresh() {
    setRefreshing(true);
    setError(null);
    try {
      await statusBoardApi.refresh();
      // Refresh returns the default view; reapply the controls currently shown.
      const result = await statusBoardApi.list({ filter, client: client || undefined, sort, order });
      setData(result);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setRefreshing(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-foreground">Status Board</h1>
          <p className="text-sm text-muted-foreground">
            {data ? `${data.rows.length} row${data.rows.length === 1 ? "" : "s"} · ` : ""}
            Read-only view of the New RFQs section in the SOQ Status Board Google Sheet.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <div className="text-right text-xs text-muted-foreground">
            {data?.last_sync_succeeded_at ? (
              <div>Last Updated {formatDateTime(data.last_sync_succeeded_at)}</div>
            ) : (
              <div>Never synced yet</div>
            )}
            {data?.last_error && (
              <div className="mt-0.5 max-w-xs text-destructive" title={data.last_error}>
                {data.last_sync_succeeded_at
                  ? "Last refresh failed — showing the previously synced board."
                  : "Last refresh failed — no successful board sync yet."}
              </div>
            )}
          </div>
          <Button variant="outline" size="sm" onClick={handleRefresh} disabled={refreshing}>
            <RefreshCw className={cn("h-3.5 w-3.5", refreshing && "animate-spin")} />
            {refreshing ? "Refreshing…" : "Refresh"}
          </Button>
          {data?.sheet_url && (
            <a href={data.sheet_url} target="_blank" rel="noreferrer">
              <Button variant="outline" size="sm">
                <ExternalLink className="h-3.5 w-3.5" />
                Open in Google Sheets
              </Button>
            </a>
          )}
        </div>
      </div>

      {cameFromDashboard && (
        <FilterChip label={`Dashboard filter: ${FILTER_LABELS[filter]}`} onClear={() => setFilter("all_active")} />
      )}

      <div className="flex flex-wrap items-center gap-2">
        <Select value={filter} onValueChange={(v) => setFilter(v as StatusBoardFilterName)}>
          <SelectTrigger className="w-48"><SelectValue /></SelectTrigger>
          <SelectContent>
            {(Object.keys(FILTER_LABELS) as StatusBoardFilterName[]).map((f) => (
              <SelectItem key={f} value={f}>{FILTER_LABELS[f]}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Input
          placeholder="Search client / location…"
          value={client}
          onChange={(e) => setClient(e.target.value)}
          className="max-w-xs"
        />
        <Select value={sort} onValueChange={(v) => setSort(v as StatusBoardSortField)}>
          <SelectTrigger className="w-44"><SelectValue /></SelectTrigger>
          <SelectContent>
            {(Object.keys(SORT_LABELS) as StatusBoardSortField[]).map((s) => (
              <SelectItem key={s} value={s}>{SORT_LABELS[s]}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={order} onValueChange={(v) => setOrder(v as "asc" | "desc")}>
          <SelectTrigger className="w-32"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="asc">Ascending</SelectItem>
            <SelectItem value="desc">Descending</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {error && <ErrorState message={error} onRetry={load} />}
      {!error && !data && <LoadingState />}
      {!error && data && <StatusBoardTable rows={data.rows} />}
    </div>
  );
}

export default function StatusBoardPage() {
  return (
    <Suspense fallback={<LoadingState />}>
      <StatusBoardPageInner />
    </Suspense>
  );
}
