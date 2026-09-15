"use client";

import { Bar, BarChart, CartesianGrid, Cell, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { colorForLabel, CHART_AXIS, CHART_GRID } from "@/lib/chart-colors";
import { formatCurrency } from "@/lib/utils";
import type { ChartBucket } from "@/types";

function ChartTooltip({ active, payload, label }: { active?: boolean; payload?: { value: number; payload: ChartBucket }[]; label?: string }) {
  if (!active || !payload?.length) return null;
  const bucket = payload[0].payload;
  return (
    <div className="rounded-md border border-border bg-card px-3 py-2 text-xs shadow-md">
      <div className="font-medium text-foreground">{label}</div>
      <div className="mt-0.5 text-muted-foreground">
        {formatCurrency(bucket.value, { compact: true })} est. fee
        {bucket.count !== null && bucket.count !== undefined ? ` · ${bucket.count} opportunit${bucket.count === 1 ? "y" : "ies"}` : ""}
      </div>
    </div>
  );
}

export function HorizontalBarChartCard({
  title,
  data,
  emptyLabel = "No data yet.",
}: {
  title: string;
  data: ChartBucket[];
  emptyLabel?: string;
}) {
  const top = data.slice(0, 8);
  return (
    <Card className="p-4">
      <CardHeader className="p-0 pb-3">
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      {top.length === 0 ? (
        <div className="flex h-40 items-center justify-center text-xs text-muted-foreground">{emptyLabel}</div>
      ) : (
        <ResponsiveContainer width="100%" height={Math.max(160, top.length * 34)}>
          <BarChart data={top} layout="vertical" margin={{ left: 8, right: 16, top: 4, bottom: 4 }} barCategoryGap={10}>
            <CartesianGrid horizontal={false} stroke={CHART_GRID} />
            <XAxis type="number" tick={{ fontSize: 11, fill: CHART_AXIS }} tickFormatter={(v) => formatCurrency(v, { compact: true })} axisLine={{ stroke: CHART_GRID }} tickLine={false} />
            <YAxis
              type="category"
              dataKey="label"
              width={140}
              tick={{ fontSize: 11, fill: CHART_AXIS }}
              axisLine={false}
              tickLine={false}
            />
            <Tooltip content={<ChartTooltip />} cursor={{ fill: "hsl(var(--secondary))" }} />
            <Bar dataKey="value" radius={[0, 4, 4, 0]} maxBarSize={18}>
              {top.map((entry) => (
                <Cell key={entry.label} fill={colorForLabel(entry.label)} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      )}
    </Card>
  );
}

export function TrendChartCard({ title, data }: { title: string; data: ChartBucket[] }) {
  return (
    <Card className="p-4">
      <CardHeader className="p-0 pb-3">
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      {data.length === 0 ? (
        <div className="flex h-40 items-center justify-center text-xs text-muted-foreground">No data yet.</div>
      ) : (
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={data} margin={{ left: 4, right: 16, top: 8, bottom: 4 }}>
            <CartesianGrid vertical={false} stroke={CHART_GRID} />
            <XAxis dataKey="label" tick={{ fontSize: 11, fill: CHART_AXIS }} axisLine={{ stroke: CHART_GRID }} tickLine={false} />
            <YAxis tick={{ fontSize: 11, fill: CHART_AXIS }} tickFormatter={(v) => formatCurrency(v, { compact: true })} axisLine={false} tickLine={false} width={56} />
            <Tooltip content={<ChartTooltip />} cursor={{ stroke: CHART_GRID }} />
            <Line type="monotone" dataKey="value" stroke="#2a78d6" strokeWidth={2} dot={{ r: 3, fill: "#2a78d6" }} activeDot={{ r: 5 }} />
          </LineChart>
        </ResponsiveContainer>
      )}
    </Card>
  );
}
