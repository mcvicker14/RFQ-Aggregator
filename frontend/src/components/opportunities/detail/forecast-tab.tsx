"use client";

import { useEffect, useState } from "react";
import { forecastApi } from "@/lib/api/resources";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { LoadingState } from "@/components/ui/states";
import { formatCurrency } from "@/lib/utils";
import type { Opportunity, RevenueForecast } from "@/types";

export function ForecastTab({ opportunity }: { opportunity: Opportunity }) {
  const [forecast, setForecast] = useState<RevenueForecast | null | undefined>(undefined);
  const [values, setValues] = useState({
    total_contract_value: "", principal_share_pct: "", estimated_fee: "", win_probability_pct: "",
    expected_award_date: "", market_sector: "",
  });
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    forecastApi.get(opportunity.id).then((f) => {
      setForecast(f);
      if (f) {
        setValues({
          total_contract_value: f.total_contract_value?.toString() ?? "",
          principal_share_pct: f.principal_share_pct?.toString() ?? "",
          estimated_fee: f.estimated_fee?.toString() ?? opportunity.estimated_fee?.toString() ?? "",
          win_probability_pct: f.win_probability_pct?.toString() ?? "",
          expected_award_date: f.expected_award_date ?? "",
          market_sector: f.market_sector ?? "",
        });
      } else {
        setValues((v) => ({ ...v, estimated_fee: opportunity.estimated_fee?.toString() ?? "" }));
      }
    });
  }, [opportunity.id, opportunity.estimated_fee]);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setSaved(false);
    try {
      const num = (v: string) => (v.trim() === "" ? null : Number(v));
      const payload = {
        total_contract_value: num(values.total_contract_value),
        principal_share_pct: num(values.principal_share_pct),
        estimated_fee: num(values.estimated_fee),
        win_probability_pct: num(values.win_probability_pct),
        expected_award_date: values.expected_award_date || null,
        market_sector: values.market_sector || null,
      };
      const updated = await forecastApi.upsert(opportunity.id, payload);
      setForecast(updated);
      setSaved(true);
    } finally {
      setBusy(false);
    }
  }

  if (forecast === undefined) return <LoadingState />;

  const weighted =
    values.estimated_fee && values.win_probability_pct
      ? (Number(values.estimated_fee) * Number(values.win_probability_pct)) / 100
      : null;

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
      <Card className="lg:col-span-2">
        <CardHeader><CardTitle>Revenue Forecast</CardTitle></CardHeader>
        <CardContent>
          <form onSubmit={save} className="grid grid-cols-2 gap-4">
            <div>
              <Label className="mb-1 block">Total Contract Value</Label>
              <Input type="number" value={values.total_contract_value} onChange={(e) => setValues((v) => ({ ...v, total_contract_value: e.target.value }))} />
            </div>
            <div>
              <Label className="mb-1 block">Principal Share (%)</Label>
              <Input type="number" min={0} max={100} value={values.principal_share_pct} onChange={(e) => setValues((v) => ({ ...v, principal_share_pct: e.target.value }))} />
            </div>
            <div>
              <Label className="mb-1 block">Estimated Principal Fee</Label>
              <Input type="number" value={values.estimated_fee} onChange={(e) => setValues((v) => ({ ...v, estimated_fee: e.target.value }))} />
            </div>
            <div>
              <Label className="mb-1 block">Win Probability (%)</Label>
              <Input type="number" min={0} max={100} value={values.win_probability_pct} onChange={(e) => setValues((v) => ({ ...v, win_probability_pct: e.target.value }))} />
            </div>
            <div>
              <Label className="mb-1 block">Expected Award Date</Label>
              <Input type="date" value={values.expected_award_date} onChange={(e) => setValues((v) => ({ ...v, expected_award_date: e.target.value }))} />
            </div>
            <div>
              <Label className="mb-1 block">Market Sector</Label>
              <Input placeholder="e.g. Water/Wastewater" value={values.market_sector} onChange={(e) => setValues((v) => ({ ...v, market_sector: e.target.value }))} />
            </div>
            <div className="col-span-2 flex items-center gap-3">
              <Button type="submit" disabled={busy}>{busy ? "Saving…" : "Save Forecast"}</Button>
              {saved && <span className="text-xs text-success">Saved.</span>}
            </div>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Weighted Value</CardTitle></CardHeader>
        <CardContent>
          <div className="text-3xl font-semibold tabular-nums text-foreground">{formatCurrency(weighted)}</div>
          <p className="mt-2 text-xs text-muted-foreground">
            Estimated Principal Fee × Win Probability. Feeds into the firm-wide pipeline forecast on the Forecast page.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
