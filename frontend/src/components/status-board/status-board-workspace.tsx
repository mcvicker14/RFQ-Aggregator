"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { statusBoardApi } from "@/lib/api/resources";
import { useAuth } from "@/lib/auth";
import { StatusBoardTable } from "./status-board-table";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { LoadingState } from "@/components/ui/states";
import { formatDateTime } from "@/lib/utils";
import type { StatusBoardFilterName, StatusBoardListResponse, StatusBoardRow, StatusBoardSortField } from "@/types";

const filters: Record<StatusBoardFilterName, string> = { all_active: "All New RFQs", submit_y: "Submit = Y", submit_n_blank: "Submit = N / blank", submitted: "Submitted", not_submitted: "Not submitted", due_soon: "Due soon", past_due: "Past due" };
const sorts: Record<StatusBoardSortField, string> = { due_date: "Due date", date_added: "Date added", client: "Client", submit_status: "Submit decision", importance: "Importance", probability: "Probability" };
const control = "h-9 rounded-md border border-input bg-background px-3 text-sm";

export function StatusBoardWorkspace({ initialFilter = "all_active" }: { initialFilter?: StatusBoardFilterName }) {
  const { user } = useAuth();
  const [data, setData] = useState<StatusBoardListResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [writeError, setWriteError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [filter, setFilter] = useState<StatusBoardFilterName>(filters[initialFilter] ? initialFilter : "all_active");
  const [client, setClient] = useState("");
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<StatusBoardSortField>("due_date");
  const [order, setOrder] = useState<"asc" | "desc">("asc");
  const [full, setFull] = useState(false);
  const [editing, setEditing] = useState<StatusBoardRow | null>(null);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [now, setNow] = useState(Date.now());
  const controls = useRef({ filter, client, sort, order });
  controls.current = { filter, client, sort, order };
  const busy = useRef(false), editRef = useRef<StatusBoardRow | null>(null), alive = useRef(true), sequence = useRef(0);
  editRef.current = editing;
  const canRefresh = ["administrator", "executive", "business_development"].includes(user?.role ?? "");
  const refreshAllowed = useRef(canRefresh); refreshAllowed.current = canRefresh;
  const canDecide = ["administrator", "executive"].includes(user?.role ?? "");

  const load = useCallback(async () => {
    const request = ++sequence.current;
    try {
      const result = await statusBoardApi.list({ ...controls.current, client: controls.current.client || undefined });
      if (alive.current && request === sequence.current) { setData(result); setError(null); }
    } catch (e) { if (alive.current && request === sequence.current) setError((e as Error).message); }
  }, []);

  const refresh = useCallback(async () => {
    if (busy.current || editRef.current || document.visibilityState === "hidden") return;
    busy.current = true; setRefreshing(true); setNow(Date.now());
    try {
      if (refreshAllowed.current) await statusBoardApi.refresh();
      await load();
    } catch (e) { if (alive.current) setError((e as Error).message); }
    finally { busy.current = false; if (alive.current) setRefreshing(false); }
  }, [load]);

  useEffect(() => {
    alive.current = true;
    const interval = window.setInterval(() => { setNow(Date.now()); void refresh(); }, 60_000);
    const onFocus = () => { void refresh(); };
    window.addEventListener("focus", onFocus); document.addEventListener("visibilitychange", onFocus);
    const initial = window.setTimeout(onFocus, 500);
    return () => { alive.current = false; sequence.current++; clearInterval(interval); clearTimeout(initial); window.removeEventListener("focus", onFocus); document.removeEventListener("visibilitychange", onFocus); };
  }, [refresh]);

  useEffect(() => {
    if (editRef.current) return;
    const timer = window.setTimeout(() => { void load(); }, 200);
    return () => clearTimeout(timer);
  }, [filter, client, sort, order, load, editing]);

  const stale = !data?.last_sync_succeeded_at || now - Date.parse(data.last_sync_succeeded_at) > 120_000;
  const editable = canDecide && !!data?.submit_edits_enabled && !stale && !data.last_error && !error && !refreshing;
  const rows = (data?.rows ?? []).filter(row => !search || [row.rfq_title, row.client_project_location, row.notes].some(v => v?.toLowerCase().includes(search.toLowerCase())));

  async function save() {
    if (!editing?.source_record_id || !editing.source_revision || (draft !== "Y" && draft !== "N") || saving) return;
    setSaving(true); setNotice(null);
    try {
      await statusBoardApi.setSubmit({ request_id: crypto.randomUUID(), source_record_id: editing.source_record_id,
        expected_revision: editing.source_revision, expected_submit: editing.submit_y_n ?? "", value: draft });
      setNotice(`Submit = ${draft} confirmed in Google Sheets.`); setEditing(null); await load();
    } catch (e) { setWriteError((e as Error).message); setEditing(null); }
    finally { setSaving(false); }
  }

  return <section className="min-w-0 space-y-4" aria-labelledby="board-heading">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><h1 id="board-heading" className="text-2xl font-semibold tracking-tight">SOQ Status Board</h1>
        <p className="mt-1 text-sm text-muted-foreground">Review New RFQs and make your Submit decisions.</p></div>
      <div className="flex items-center gap-3">
        {data?.sheet_url && <a className="text-sm text-primary hover:underline" href={data.sheet_url} target="_blank" rel="noreferrer">Open Google Sheets</a>}
        <Button variant="outline" size="sm" onClick={() => { setWriteError(null); void refresh(); }} disabled={refreshing || !!editing}>{refreshing ? "Refreshing…" : "Refresh"}</Button>
      </div>
    </div>
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground" role="status">
      <span>{data?.last_sync_succeeded_at ? `Checked ${formatDateTime(data.last_sync_succeeded_at)}` : "No successful sheet refresh yet"}</span>
      <span>{canRefresh ? "Checks Google Sheets every minute while open" : "Checks the cached board every minute while open"}</span>
      <span>Free hosting may delay checks.</span>
    </div>
    {(error || data?.last_error || stale) && <p role="alert" className="text-sm text-destructive">{error || data?.last_error || "This snapshot is older than two minutes. Refresh before editing."}{data && " Showing the last available board."}</p>}
    {notice && <p role="status" className="text-sm text-success">{notice}</p>}
    {writeError && <p role="alert" className="text-sm text-destructive">{writeError}</p>}
    {canDecide && !data?.submit_edits_enabled && <p className="text-xs text-muted-foreground">Y/N editing awaits activation. Google Sheets remains available.</p>}
    <div className="flex flex-wrap gap-2">
      <Input aria-label="Search RFQs, clients and notes" placeholder="Search RFQs, clients, notes" value={search} onChange={e => setSearch(e.target.value)} className="w-full sm:max-w-xs" />
      <select aria-label="Filter Status Board" className={control} value={filter} onChange={e => setFilter(e.target.value as StatusBoardFilterName)} disabled={!!editing}>{Object.entries(filters).map(([v, label]) => <option key={v} value={v}>{label}</option>)}</select>
      <Button size="sm" variant="ghost" onClick={() => setFull(!full)}>{full ? "Focused view" : "All columns"}</Button>
      <span className="ml-auto self-center text-xs text-muted-foreground">{rows.length} RFQ{rows.length === 1 ? "" : "s"}</span>
    </div>
    <details className="text-sm"><summary className="w-fit cursor-pointer text-muted-foreground">More filters and sorting</summary><div className="mt-2 flex flex-wrap gap-2">
      <Input aria-label="Client or location filter" placeholder="Client / location" value={client} onChange={e => setClient(e.target.value)} disabled={!!editing} className="max-w-xs" />
      <select aria-label="Sort Status Board" className={control} value={sort} onChange={e => setSort(e.target.value as StatusBoardSortField)} disabled={!!editing}>{Object.entries(sorts).map(([v, label]) => <option key={v} value={v}>{label}</option>)}</select>
      <select aria-label="Sort direction" className={control} value={order} onChange={e => setOrder(e.target.value as "asc" | "desc")} disabled={!!editing}><option value="asc">Ascending</option><option value="desc">Descending</option></select>
    </div></details>
    {editing && <form onSubmit={e => { e.preventDefault(); void save(); }} className="rounded-md border border-primary/30 bg-card p-4" aria-label="Edit Submit decision">
      <p className="mb-3 text-sm font-medium">{editing.rfq_title}</p>
      <div className="flex flex-wrap items-center gap-2"><label htmlFor="submit-decision" className="text-sm">Submit? (currently {editing.submit_y_n || "blank"})</label>
        <Input id="submit-decision" autoFocus maxLength={1} value={draft} onChange={e => setDraft(e.target.value.toUpperCase())} className="w-16" disabled={saving} />
        <Button size="sm" type="submit" disabled={saving || (draft !== "Y" && draft !== "N")}>{saving ? "Confirming…" : "Save to sheet"}</Button>
        <Button size="sm" type="button" variant="ghost" disabled={saving} onClick={() => setEditing(null)}>Cancel</Button></div>
      <p className="mt-2 text-xs text-muted-foreground">Only Submit? changes. Detected conflicts stop the save. No automatic retry.</p>
    </form>}
    {!data ? <LoadingState label="Loading Status Board…" /> : <StatusBoardTable rows={rows} compact={!full}
      editEnabled={editable && !writeError}
      onEdit={canDecide && data.submit_edits_enabled && !editing ? row => { setEditing({ ...row }); setDraft(""); setNotice(null); } : undefined} />}
  </section>;
}
