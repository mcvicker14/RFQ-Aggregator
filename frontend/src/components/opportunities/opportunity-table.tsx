"use client";

import { useRouter } from "next/navigation";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ScoreBadge, SampleDataBadge, SetAsideBadge } from "@/components/domain/badges";
import { EmptyState } from "@/components/ui/states";
import { formatCurrency, formatDate, daysUntil, cn } from "@/lib/utils";
import type { OpportunityListItem } from "@/types";

export function OpportunityTable({ opportunities, emptyMessage }: { opportunities: OpportunityListItem[]; emptyMessage?: string }) {
  const router = useRouter();

  if (opportunities.length === 0) {
    return <EmptyState title="No opportunities found" description={emptyMessage ?? "Try adjusting your filters, or add a new opportunity."} />;
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="w-20">Score</TableHead>
          <TableHead>Opportunity</TableHead>
          <TableHead>Agency</TableHead>
          <TableHead>Set-Aside</TableHead>
          <TableHead className="text-right">Est. Fee</TableHead>
          <TableHead>Due</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {opportunities.map((opp) => {
          const due = daysUntil(opp.proposal_due_at);
          return (
            <TableRow key={opp.id} onClick={() => router.push(`/opportunities/${opp.id}`)} className="cursor-pointer">
              <TableCell>
                <ScoreBadge score={opp.current_score} band={opp.current_score_band} />
              </TableCell>
              <TableCell className="max-w-[320px]">
                <div className="flex items-center gap-2">
                  <span className="truncate font-medium text-foreground">{opp.title}</span>
                  {opp.is_sample_data && <SampleDataBadge />}
                </div>
                <div className="text-xs text-muted-foreground">{opp.solicitation_number ?? "No solicitation number yet"}</div>
              </TableCell>
              <TableCell className="text-xs text-muted-foreground">
                {opp.agency?.short_name ?? opp.agency?.name ?? "Unassigned"}
                {opp.location_state ? ` · ${opp.location_state}` : ""}
              </TableCell>
              <TableCell>
                <SetAsideBadge value={opp.set_aside} />
              </TableCell>
              <TableCell className="text-right tabular-nums">{formatCurrency(opp.estimated_fee, { compact: true })}</TableCell>
              <TableCell>
                <div className={cn("text-xs", due !== null && due <= 7 && due >= 0 && "font-semibold text-destructive")}>
                  {formatDate(opp.proposal_due_at)}
                </div>
                {due !== null && (
                  <div className="text-[11px] text-muted-foreground">{due < 0 ? "Past due" : `${due}d left`}</div>
                )}
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}
