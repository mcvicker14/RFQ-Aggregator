"use client";

import { useEffect, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import { Bell, LogOut, Search } from "lucide-react";
import { useAuth } from "@/lib/auth";
import { alertsApi } from "@/lib/api/resources";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import type { Alert } from "@/types";

// Mirrors sidebar.tsx's routes (deliberately not imported from there, to keep the
// sidebar's grouping structure free to change independently of this lookup) — gives
// the topbar a page-title breadcrumb without touching every page's own content.
const PAGE_TITLES: { href: string; label: string }[] = [
  { href: "/discover", label: "Discover" },
  { href: "/sources", label: "Intelligence Sources" },
  { href: "/opportunities", label: "Opportunities" },
  { href: "/pipeline", label: "Pipeline" },
  { href: "/tasks", label: "Tasks" },
  { href: "/agencies", label: "Agencies" },
  { href: "/companies", label: "Companies" },
  { href: "/contacts", label: "Contacts" },
  { href: "/forecast", label: "Forecast" },
  { href: "/settings", label: "Settings" },
  { href: "/", label: "Dashboard" },
];

function pageTitleFor(pathname: string): string {
  const match = PAGE_TITLES.find((p) => (p.href === "/" ? pathname === "/" : pathname.startsWith(p.href)));
  return match?.label ?? "Principal Opportunity Intelligence";
}

export function Topbar() {
  const { user, logout } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
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
    <header className="flex h-16 items-center gap-6 border-b border-border bg-card px-6">
      <h1 className="shrink-0 text-base font-semibold tracking-tight text-foreground">{pageTitleFor(pathname)}</h1>

      <form onSubmit={handleSearch} className="max-w-md flex-1">
        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground/70" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search opportunities, agencies, companies…"
            className="border-transparent bg-secondary/70 pl-9 shadow-none focus-visible:border-ring focus-visible:bg-card"
          />
        </div>
      </form>

      <div className="ml-auto flex items-center gap-1">
        <div className="relative">
          <Button variant="ghost" size="icon" onClick={() => setShowAlerts((v) => !v)} aria-label="Alerts">
            <Bell className="h-4 w-4" />
            {alerts.length > 0 && (
              <span className="absolute right-1.5 top-1.5 flex h-3.5 w-3.5 items-center justify-center rounded-full bg-destructive text-[9px] font-bold text-destructive-foreground">
                {alerts.length > 9 ? "9+" : alerts.length}
              </span>
            )}
          </Button>
          {showAlerts && (
            <div className="absolute right-0 z-40 mt-2 w-80 rounded-lg border border-border bg-card shadow-lg">
              <div className="border-b border-border px-3.5 py-2.5 text-xs font-semibold text-muted-foreground">
                Unread Alerts
              </div>
              <div className="max-h-80 overflow-y-auto">
                {alerts.length === 0 && <div className="px-3.5 py-4 text-xs text-muted-foreground">No unread alerts.</div>}
                {alerts.map((a) => (
                  <button
                    key={a.id}
                    onClick={async () => {
                      await alertsApi.markRead(a.id);
                      setAlerts((prev) => prev.filter((x) => x.id !== a.id));
                      if (a.opportunity_id) router.push(`/opportunities/${a.opportunity_id}`);
                    }}
                    className="block w-full border-b border-border px-3.5 py-2.5 text-left text-xs last:border-0 hover:bg-secondary"
                  >
                    <div className="font-medium text-foreground">{a.title}</div>
                    {a.body && <div className="mt-0.5 text-muted-foreground">{a.body}</div>}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>

        <div className={cn("ml-2 flex items-center gap-2.5 pl-3", "border-l border-border")}>
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
