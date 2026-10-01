import Link from "next/link";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/states";
import type { StatusBoardRow } from "@/types";

// Exact 16 New RFQs columns from the product spec, in sheet order — this app is
// read-only for every one of these in this first version (the Google Sheet remains
// authoritative for Submit?, Importance, Quality, Probability, Notes, Submitted Y/N),
// so every cell below renders the raw value exactly as the sheet has it, never
// reformatted or reinterpreted.
function cell(value: string | null, className = "") {
  if (!value) return <TableCell className={className}>—</TableCell>;
  return (
    <TableCell className={className} title={value.length > 40 ? value : undefined}>
      <span className="line-clamp-2">{value}</span>
    </TableCell>
  );
}

export function StatusBoardTable({ rows }: { rows: StatusBoardRow[] }) {
  if (rows.length === 0) {
    return (
      <EmptyState
        title="No Status Board rows match this view"
        description="Try a different filter, or Refresh if the board was just updated in Google Sheets."
      />
    );
  }

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
                {row.is_submit_y ? (
                  <Badge variant="accent">Y</Badge>
                ) : (
                  <span className="text-muted-foreground">{row.submit_y_n || "—"}</span>
                )}
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
