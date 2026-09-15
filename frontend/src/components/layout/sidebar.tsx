"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  Search,
  Briefcase,
  Columns3,
  CheckSquare,
  Building2,
  Users2,
  Contact2,
  TrendingUp,
  Settings,
} from "lucide-react";
import { cn } from "@/lib/utils";

const NAV_ITEMS = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/discover", label: "Discover", icon: Search },
  { href: "/opportunities", label: "Opportunities", icon: Briefcase },
  { href: "/pipeline", label: "Pipeline", icon: Columns3 },
  { href: "/tasks", label: "Tasks", icon: CheckSquare },
  { href: "/agencies", label: "Agencies", icon: Building2 },
  { href: "/companies", label: "Companies", icon: Users2 },
  { href: "/contacts", label: "Contacts", icon: Contact2 },
  { href: "/forecast", label: "Forecast", icon: TrendingUp },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="hidden w-56 shrink-0 flex-col border-r border-border bg-card md:flex">
      <div className="flex h-16 flex-col justify-center border-b border-border px-4">
        <span className="text-sm font-semibold leading-tight text-foreground">Principal Opportunity</span>
        <span className="text-sm font-semibold leading-tight text-foreground">Intelligence</span>
      </div>
      <nav className="flex-1 space-y-0.5 px-2 py-3">
        {NAV_ITEMS.map((item) => {
          const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm font-medium transition-colors",
                active ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-secondary hover:text-foreground"
              )}
            >
              <Icon className="h-4 w-4" />
              {item.label}
            </Link>
          );
        })}
      </nav>
      <div className="border-t border-border px-4 py-3 text-[11px] leading-snug text-muted-foreground">
        Find Earlier. Pursue Smarter.
        <br />
        Win More.
      </div>
    </aside>
  );
}
