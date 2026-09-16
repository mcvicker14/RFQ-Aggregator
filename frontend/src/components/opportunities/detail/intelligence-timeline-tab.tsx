"use client";

import { useEffect, useState } from "react";
import { intelligenceItemsApi } from "@/lib/api/resources";
import { Card, CardContent } from "@/components/ui/card";
import { EmptyState, LoadingState } from "@/components/ui/states";
import { IntelligenceCategoryBadge } from "@/components/domain/badges";
import { formatDateTime } from "@/lib/utils";
import type { IntelligenceItem } from "@/types";

export function IntelligenceTimelineTab({ opportunityId }: { opportunityId: string }) {
  const [items, setItems] = useState<IntelligenceItem[] | null>(null);

  useEffect(() => {
    intelligenceItemsApi.timeline(opportunityId).then(setItems).catch(() => setItems([]));
  }, [opportunityId]);

  if (!items) return <LoadingState />;
  if (items.length === 0) {
    return (
      <EmptyState
        title="No intelligence history yet"
        description="This opportunity wasn't discovered through a connected source, or no other source has reported on it yet."
      />
    );
  }

  return (
    <Card>
      <CardContent className="p-4">
        <p className="mb-4 text-xs text-muted-foreground">
          Every appearance of this project across connected sources, oldest first — including any early signal or
          pre-solicitation notice that preceded it becoming a live opportunity.
        </p>
        <ol className="relative flex flex-col gap-5 border-l border-border pl-5">
          {items.map((item) => (
            <li key={item.id} className="relative">
              <span className="absolute -left-[25px] top-1 h-2.5 w-2.5 rounded-full border-2 border-card bg-primary" />
              <div className="flex flex-wrap items-center gap-2">
                <IntelligenceCategoryBadge value={item.intelligence_category} />
                <span className="text-sm font-medium text-foreground">{item.title}</span>
              </div>
              <div className="mt-1 text-xs text-muted-foreground">
                {item.source}
                {item.agency_name && ` · ${item.agency_name}`}
                {item.location_state && ` · ${item.location_state}`}
                {item.early_signal_score !== null && ` · Early Signal Score ${item.early_signal_score}/100`}
              </div>
              <div className="mt-0.5 text-[11px] text-muted-foreground">First detected {formatDateTime(item.first_detected_at)}</div>
            </li>
          ))}
        </ol>
      </CardContent>
    </Card>
  );
}
