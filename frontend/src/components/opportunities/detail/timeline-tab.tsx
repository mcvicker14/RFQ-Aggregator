"use client";

import { useEffect, useState } from "react";
import { opportunitiesApi } from "@/lib/api/resources";
import { Card, CardContent } from "@/components/ui/card";
import { EmptyState, LoadingState } from "@/components/ui/states";
import { formatDateTime, titleCase } from "@/lib/utils";
import type { Activity } from "@/types";

export function TimelineTab({ opportunityId }: { opportunityId: string }) {
  const [activities, setActivities] = useState<Activity[] | null>(null);

  useEffect(() => {
    opportunitiesApi.activities(opportunityId).then((a) => setActivities(a as Activity[])).catch(() => setActivities([]));
  }, [opportunityId]);

  if (!activities) return <LoadingState />;
  if (activities.length === 0) return <EmptyState title="No activity yet" />;

  return (
    <Card>
      <CardContent className="p-4">
        <ol className="relative flex flex-col gap-5 border-l border-border pl-5">
          {activities.map((a) => (
            <li key={a.id} className="relative">
              <span className="absolute -left-[25px] top-1 h-2.5 w-2.5 rounded-full border-2 border-card bg-primary" />
              <div className="text-sm text-foreground">{a.description}</div>
              {a.detail && <div className="mt-0.5 text-xs text-muted-foreground">{a.detail}</div>}
              <div className="mt-0.5 text-[11px] text-muted-foreground">
                {titleCase(a.activity_type)} · {formatDateTime(a.created_at)}
              </div>
            </li>
          ))}
        </ol>
      </CardContent>
    </Card>
  );
}
