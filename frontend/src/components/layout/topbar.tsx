"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Bell, LogOut, Search } from "lucide-react";
import { useAuth } from "@/lib/auth";
import { alertsApi } from "@/lib/api/resources";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { Alert } from "@/types";

export function Topbar() {
  const { user, logout } = useAuth();
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [showAlerts, setShowAlerts] = useState(false);

  useEffect(() => {
    alertsApi
      .list(true)
      .then(setAlerts)
      .catch(() => setAlerts([]));
  }, []);

  function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    router.push(`/opportunities?q=${encodeURIComponent(query)}`);
  }

  return (
    <header className="flex h-16 items-center gap-4 border-b border-border bg-card px-6">
      <form onSubmit={handleSearch} className="flex-1 max-w-md">
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search opportunities, agencies, companies…"
            className="pl-8"
          />
        </div>
      </form>

      <div className="ml-auto flex items-center gap-3">
        <div className="relative">
          <Button variant="ghost" size="icon" onClick={() => setShowAlerts((v) => !v)} aria-label="Alerts">
            <Bell className="h-4 w-4" />
            {alerts.length > 0 && (
              <span className="absolute right-1 top-1 flex h-3.5 w-3.5 items-center justify-center rounded-full bg-destructive text-[9px] font-bold text-destructive-foreground">
                {alerts.length > 9 ? "9+" : alerts.length}
              </span>
            )}
          </Button>
          {showAlerts && (
            <div className="absolute right-0 z-40 mt-2 w-80 rounded-md border border-border bg-card shadow-lg">
              <div className="border-b border-border px-3 py-2 text-xs font-semibold text-muted-foreground">
                Unread Alerts
              </div>
              <div className="max-h-80 overflow-y-auto">
                {alerts.length === 0 && <div className="px-3 py-4 text-xs text-muted-foreground">No unread alerts.</div>}
                {alerts.map((a) => (
                  <button
                    key={a.id}
                    onClick={async () => {
                      await alertsApi.markRead(a.id);
                      setAlerts((prev) => prev.filter((x) => x.id !== a.id));
                      if (a.opportunity_id) router.push(`/opportunities/${a.opportunity_id}`);
                    }}
                    className="block w-full border-b border-border px-3 py-2 text-left text-xs last:border-0 hover:bg-secondary"
                  >
                    <div className="font-medium text-foreground">{a.title}</div>
                    {a.body && <div className="mt-0.5 text-muted-foreground">{a.body}</div>}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>

        <div className="flex items-center gap-2 border-l border-border pl-3">
          <div className="text-right leading-tight">
            <div className="text-xs font-medium text-foreground">{user?.full_name}</div>
            <div className="text-[10px] capitalize text-muted-foreground">{user?.role.replace(/_/g, " ")}</div>
          </div>
          <Button variant="ghost" size="icon" onClick={logout} aria-label="Log out">
            <LogOut className="h-4 w-4" />
          </Button>
        </div>
      </div>
    </header>
  );
}
