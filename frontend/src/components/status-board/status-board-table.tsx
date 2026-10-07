import Link from "next/link";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/states";
import type { StatusBoardRow } from "@/types";

// The focused view keeps daily decisions visible; all 16 raw sheet fields remain
// available in the expanded view. Only Submit? has an owner-driven edit action.
function cell(value: string | null, className = "") {
  if (!value) return <TableCell className={className}>—</TableCell>;
  return (
    <TableCell className={className} title={value.length > 40 ? value : undefined}>
      <span className="line-clamp-2">{value}</span>
    </TableCell>
  );
}

export function StatusBoardTable({ rows, compact = false, onEdit, editEnabled = true }: { rows: StatusBoardRow[]; compact?: boolean; onEdit?: (row: StatusBoardRow) => void; editEnabled?: boolean }) {
  if (rows.length === 0) {
    return (
      <EmptyState
        title="No Status Board rows match this view"
        description="Try a different filter, or Refresh if the board was just updated in Google Sheets."
      />
    );
  }

  function decision(row: StatusBoardRow) {
    const usable = editEnabled && !!row.source_record_id && !!row.source_revision && !row.is_submitted_y;
    return <div className="flex items-center gap-2"><span className={row.is_submit_y ? "font-semibold text-primary" : "text-muted-foreground"}>{row.submit_y_n || "—"}</span>
      {onEdit && <button type="button" disabled={!usable} onClick={() => onEdit(row)}
        aria-label={`${row.submit_y_n ? "Change" : "Choose"} Submit for ${row.rfq_title}`} title={usable ? "Choose a Submit decision" : "Refresh and review the sheet; source identity setup may be required"}
        className="rounded px-2 py-1 text-xs text-primary hover:bg-secondary disabled:cursor-not-allowed disabled:text-muted-foreground">{row.submit_y_n ? "Change" : "Choose"}</button>}</div>;
  }

  if (compact) return <>
    <div className="divide-y divide-border rounded-lg border border-border bg-card md:hidden">{rows.map(row => <article key={row.id} className="space-y-2 p-3">
      <div className="font-medium">{row.opportunity_id ? <Link href={`/opportunities/${row.opportunity_id}`} className="text-primary hover:underline">{row.rfq_title}</Link> : row.rfq_title}</div>
      <p className="text-xs text-muted-foreground">{row.client_project_location || "—"}</p>
      <div className="flex flex-wrap items-center justify-between gap-2"><div className="text-xs">Due {row.due_date || "—"} {row.due_time}</div><div className="flex items-center gap-2 text-sm"><span className="text-xs text-muted-foreground">Submit?</span>{decision(row)}</div></div>
      {row.is_submitted_y && <Badge variant="success">Submitted</Badge>}
      <div className="flex items-start justify-between gap-3"><p className="text-xs text-muted-foreground">{row.notes || "No notes"}</p>{row.link && <a href={row.link} target="_blank" rel="noreferrer" className="shrink-0 text-xs text-primary hover:underline">Source</a>}</div>
    </article>)}</div>
    <div className="hidden rounded-lg border border-border bg-card md:block"><Table>
    <TableHeader><TableRow><TableHead className="min-w-[220px]">RFQ / Client</TableHead><TableHead>Due</TableHead><TableHead>Submit?</TableHead><TableHead className="min-w-[180px]">Notes</TableHead><TableHead>Link</TableHead></TableRow></TableHeader>
    <TableBody>{rows.map(row => <TableRow key={row.id}>
      <TableCell><div className="max-w-md font-medium">{row.opportunity_id ? <Link href={`/opportunities/${row.opportunity_id}`} className="text-primary hover:underline">{row.rfq_title}</Link> : row.rfq_title}</div><div className="mt-1 text-xs text-muted-foreground">{row.client_project_location || "—"}</div></TableCell>
      <TableCell className="whitespace-nowrap">{row.due_date || "—"}<div className="text-xs text-muted-foreground">{row.due_time}</div></TableCell>
      <TableCell>{decision(row)}{row.is_submitted_y && <Badge variant="success">Submitted</Badge>}</TableCell>
      {cell(row.notes, "max-w-[300px]")}
      <TableCell>{row.link ? <a href={row.link} target="_blank" rel="noreferrer" className="text-primary hover:underline" aria-label={`Open source for ${row.rfq_title}`}>Open</a> : "—"}</TableCell>
    </TableRow>)}</TableBody>
  </Table></div></>;

  return (
    <div className="rounded-lg border border-border bg-card">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Date Added</TableHead>
            <TableHead>Due Date</TableHead>
            <TableHead>Due Time</TableHead>
            <TableHead>Client / Project Location</TableHead>
            <TableHead className="min-w-[220px]">RFQ Title</TableHead>
            <TableHead>Digital Option</TableHead>
            <TableHead>Standard Form</TableHead>
            <TableHead>Submit?</TableHead>
            <TableHead>Date Submitted</TableHead>
            <TableHead>Importance</TableHead>
            <TableHead>Quality</TableHead>
            <TableHead>Probability</TableHead>
            <TableHead>Go-By(s)</TableHead>
            <TableHead className="min-w-[180px]">Notes</TableHead>
            <TableHead>Submitted?</TableHead>
            <TableHead>Link</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.id} className={row.is_submit_y ? "bg-accent/5" : undefined}>
              {cell(row.date_added)}
              {cell(row.due_date)}
              {cell(row.due_time)}
              {cell(row.client_project_location)}
              <TableCell>
                <div className="flex flex-col gap-1">
                  {row.opportunity_id ? (
                    <Link href={`/opportunities/${row.opportunity_id}`} className="font-medium text-primary hover:underline">
                      {row.rfq_title || "(untitled)"}
                    </Link>
                  ) : (
                    <span className="font-medium text-foreground">{row.rfq_title || "(untitled)"}</span>
                  )}
                  {row.is_manual_entry && (
                    <Badge variant="muted" className="w-fit">Manual Status Board Entry</Badge>
                  )}
                </div>
              </TableCell>
              {cell(row.digital_option)}
              {cell(row.standard_form)}
              <TableCell>
                {decision(row)}
              </TableCell>
              {cell(row.date_submitted)}
              {cell(row.importance)}
              {cell(row.quality)}
              {cell(row.probability)}
              {cell(row.go_bys)}
              {cell(row.notes, "max-w-[220px]")}
              <TableCell>
                {row.is_submitted_y ? (
                  <Badge variant="success">Y</Badge>
                ) : (
                  <span className="text-muted-foreground">{row.submitted_y_n || "—"}</span>
                )}
              </TableCell>
              <TableCell>
                {row.link ? (
                  <a href={row.link} target="_blank" rel="noreferrer" className="text-primary hover:underline">
                    Open
                  </a>
                ) : (
                  <span className="text-muted-foreground">—</span>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
