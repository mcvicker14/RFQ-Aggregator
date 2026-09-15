"use client";

import { useEffect, useState } from "react";
import { forecastApi } from "@/lib/api/resources";
import { KpiCard } from "@/components/dashboard/kpi-card";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { LoadingState, ErrorState } from "@/components/ui/states";
import { formatCurrency } from "@/lib/utils";
import { DollarSign, Target, TrendingDown, TrendingUp } from "lucide-react";
import type { ForecastBucket, ForecastSummary } from "@/types";

function BucketTable({ title, buckets }: { title: string; buckets: ForecastBucket[] }) {
  return (
    <Card>
      <CardHeader><CardTitle>{title}</CardTitle></CardHeader>
      <CardContent>
        {buckets.length === 0 ? (
          <p className="text-xs text-muted-foreground">No data yet.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] text-muted-foreground">
                <th className="pb-2 font-medium">Period</th>
                <th className="pb-2 text-right font-medium">Total Pipeline</th>
                <th className="pb-2 text-right font-medium">Weighted</th>
                <th className="pb-2 text-right font-medium">Opportunities</th>
              </tr>
            </thead>
            <tbody>
              {buckets.map((b) => (
                <tr key={b.label} className="border-t border-border">
                  <td className="py-1.5 text-foreground">{b.label}</td>
                  <td className="py-1.5 text-right tabular-nums">{formatCurrency(b.total_pipeline, { compact: true })}</td>
                  <td className="py-1.5 text-right tabular-nums text-accent-foreground">{formatCurrency(b.weighted_pipeline, { compact: true })}</td>
                  <td className="py-1.5 text-right tabular-nums text-muted-foreground">{b.opportunity_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </CardContent>
    </Card>
  );
}

export default function ForecastPage() {
  const [data, setData] = useState<ForecastSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  function load() {
    setError(null);
    forecastApi.summary(new Date().getFullYear().toString()).then(setData).catch((e) => setError(e.message));
  }
  useEffect(load, []);

  if (error) return <ErrorState message={error} onRetry={load} />;
  if (!data) return <LoadingState />;

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold text-foreground">Revenue Forecast</h1>
        <p className="text-sm text-muted-foreground">Weighted pipeline value = Estimated Principal Fee × Win Probability.</p>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
        <KpiCard label="Total Pipeline" value={formatCurrency(data.total_pipeline, { compact: true })} icon={DollarSign} />
        <KpiCard label="Weighted Pipeline" value={formatCurrency(data.weighted_pipeline, { compact: true })} icon={TrendingUp} tone="accent" />
        <KpiCard label="Committed Revenue" value={formatCurrency(data.committed_revenue, { compact: true })} icon={Target} tone="success" />
        <KpiCard label="Target Revenue" value={formatCurrency(data.target_revenue, { compact: true })} icon={Target} />
        <KpiCard label="Revenue Gap" value={formatCurrency(data.revenue_gap, { compact: true })} icon={TrendingDown} tone={data.revenue_gap > 0 ? "warning" : "success"} />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <BucketTable title="By Month" buckets={data.by_month} />
        <BucketTable title="By Quarter" buckets={data.by_quarter} />
        <BucketTable title="By Agency" buckets={data.by_agency} />
        <BucketTable title="By Market Sector" buckets={data.by_market_sector} />
      </div>
    </div>
  );
}
