"use client";

import { useEffect, useState } from "react";
import { settingsApi, pipelineStagesApi, usersApi } from "@/lib/api/resources";
import { useAuth } from "@/lib/auth";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { LoadingState } from "@/components/ui/states";
import { titleCase } from "@/lib/utils";
import type { PipelineStage, User } from "@/types";

const CATEGORY_LABELS: Record<string, string> = {
  strategic_fit: "Strategic Fit", customer_fit: "Customer Fit", contract_fit: "Contract Fit",
  geographic_fit: "Geographic Fit", competitive_advantage: "Competitive Advantage",
  financial_attractiveness: "Financial Attractiveness", competition: "Competition", timing: "Timing",
};

export default function SettingsPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "administrator";

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-xl font-semibold text-foreground">Settings</h1>
        <p className="text-sm text-muted-foreground">Scoring configuration, pipeline stages, and user administration.</p>
      </div>

      <Tabs defaultValue="scoring">
        <TabsList>
          <TabsTrigger value="scoring">Scoring Weights</TabsTrigger>
          <TabsTrigger value="stages">Pipeline Stages</TabsTrigger>
          <TabsTrigger value="users">Users</TabsTrigger>
          <TabsTrigger value="data">Sample Data</TabsTrigger>
        </TabsList>
        <TabsContent value="scoring"><ScoringWeightsPanel isAdmin={isAdmin} /></TabsContent>
        <TabsContent value="stages"><StagesPanel /></TabsContent>
        <TabsContent value="users"><UsersPanel isAdmin={isAdmin} /></TabsContent>
        <TabsContent value="data"><SampleDataPanel isAdmin={isAdmin} /></TabsContent>
      </Tabs>
    </div>
  );
}

function ScoringWeightsPanel({ isAdmin }: { isAdmin: boolean }) {
  const [weights, setWeights] = useState<Record<string, number> | null>(null);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);

  function load() {
    settingsApi.getScoringWeights().then((w) => setWeights(w.weights)).catch(() => setWeights(null));
  }
  useEffect(load, []);

  async function save() {
    if (!weights) return;
    setBusy(true);
    setSaved(false);
    try {
      await settingsApi.updateScoringWeights({ weights });
      setSaved(true);
    } finally {
      setBusy(false);
    }
  }

  if (!weights) return <LoadingState />;
  const total = Object.values(weights).reduce((a, b) => a + b, 0);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Principal Pursuit Score — Category Weights</CardTitle>
        <CardDescription>
          Controls how much each category contributes to the 0–100 score. Weights should sum to 100. See
          docs/SCORING_METHODOLOGY.md for what drives each category.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {Object.entries(weights).map(([key, value]) => (
          <div key={key} className="flex items-center justify-between gap-4">
            <span className="text-sm text-foreground">{CATEGORY_LABELS[key] ?? titleCase(key)}</span>
            <Input
              type="number"
              className="w-24"
              value={value}
              disabled={!isAdmin}
              onChange={(e) => setWeights((w) => (w ? { ...w, [key]: Number(e.target.value) } : w))}
            />
          </div>
        ))}
        <div className="flex items-center justify-between border-t border-border pt-3 text-sm">
          <span className="text-muted-foreground">Total</span>
          <span className={total === 100 ? "font-medium text-success" : "font-medium text-warning"}>{total}</span>
        </div>
        {isAdmin ? (
          <div className="flex items-center gap-3">
            <Button onClick={save} disabled={busy}>{busy ? "Saving…" : "Save Weights"}</Button>
            {saved && <span className="text-xs text-success">Saved. New scores will use these weights.</span>}
          </div>
        ) : (
          <p className="text-xs text-muted-foreground">Only an Administrator can change scoring weights.</p>
        )}
      </CardContent>
    </Card>
  );
}

function StagesPanel() {
  const [stages, setStages] = useState<PipelineStage[] | null>(null);
  useEffect(() => {
    pipelineStagesApi.list().then(setStages).catch(() => setStages([]));
  }, []);
  if (!stages) return <LoadingState />;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Pipeline Stages</CardTitle>
        <CardDescription>The default business-development workflow, spec §18. Ordered left to right.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-wrap gap-2">
        {stages.map((s) => (
          <Badge key={s.id} variant={s.is_closed_won ? "success" : s.is_closed_lost ? "destructive" : "secondary"}>
            {s.sort_order + 1}. {s.name}
          </Badge>
        ))}
      </CardContent>
    </Card>
  );
}

function UsersPanel({ isAdmin }: { isAdmin: boolean }) {
  const [users, setUsers] = useState<User[] | null>(null);
  useEffect(() => {
    usersApi.list().then(setUsers).catch(() => setUsers([]));
  }, []);
  if (!users) return <LoadingState />;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Users</CardTitle>
        <CardDescription>
          {isAdmin ? "Role-based access control per docs/SECURITY.md." : "Contact an Administrator to add or change users."}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        {users.map((u) => (
          <div key={u.id} className="flex items-center justify-between border-b border-border py-2 last:border-0">
            <div>
              <div className="text-sm font-medium text-foreground">{u.full_name}</div>
              <div className="text-xs text-muted-foreground">{u.email}</div>
            </div>
            <Badge variant="outline">{titleCase(u.role)}</Badge>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function SampleDataPanel({ isAdmin }: { isAdmin: boolean }) {
  const [hideByDefault, setHideByDefault] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    settingsApi.getHideSampleData().then((r) => setHideByDefault(r.hide_sample_data_by_default)).catch(() => setHideByDefault(false));
  }, []);

  async function toggle() {
    if (hideByDefault === null) return;
    setBusy(true);
    try {
      const result = await settingsApi.setHideSampleData(!hideByDefault);
      setHideByDefault(result.hide_sample_data_by_default);
    } finally {
      setBusy(false);
    }
  }

  if (hideByDefault === null) return <LoadingState />;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Sample Data</CardTitle>
        <CardDescription>
          The app ships with realistic SAMPLE DATA opportunities so you can see it in action — every one is clearly
          labeled and never counted as a real pursuit unless you choose to include it. This setting controls whether
          the Dashboard's numbers include that sample data by default.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="flex items-center justify-between rounded-md border border-border p-3">
          <div>
            <div className="text-sm font-medium text-foreground">Hide sample data from the Dashboard by default</div>
            <div className="text-xs text-muted-foreground">
              {hideByDefault
                ? "Dashboard totals currently exclude SAMPLE DATA opportunities."
                : "Dashboard totals currently include SAMPLE DATA opportunities (unchanged from how this app has always behaved)."}
            </div>
          </div>
          {isAdmin ? (
            <Button size="sm" variant={hideByDefault ? "default" : "outline"} onClick={toggle} disabled={busy}>
              {hideByDefault ? "Enabled" : "Disabled"}
            </Button>
          ) : (
            <Badge variant="outline">{hideByDefault ? "Enabled" : "Disabled"}</Badge>
          )}
        </div>
        {!isAdmin && <p className="text-xs text-muted-foreground">Only an Administrator can change this setting.</p>}
        <p className="text-xs text-muted-foreground">
          Sample data can also be hidden per-view — e.g. on Discover — without changing this app-wide default.
        </p>
      </CardContent>
    </Card>
  );
}
