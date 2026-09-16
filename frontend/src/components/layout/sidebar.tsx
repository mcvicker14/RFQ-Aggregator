"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  Search,
  Radar,
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
import type { LucideIcon } from "lucide-react";

interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
}

// Grouped only for visual scanability in the sidebar below — every item, label, and
// route is unchanged from before. Settings lives on its own near the footer, the
// conventional place for account/admin-level navigation.
const NAV_SECTIONS: { label: string; items: NavItem[] }[] = [
  { label: "Overview", items: [{ href: "/", label: "Dashboard", icon: LayoutDashboard }] },
  {
    label: "Intelligence",
    items: [
      { href: "/discover", label: "Discover", icon: Search },
      { href: "/sources", label: "Intelligence Sources", icon: Radar },
    ],
  },
  {
    label: "Pipeline",
    items: [
      { href: "/opportunities", label: "Opportunities", icon: Briefcase },
      { href: "/pipeline", label: "Pipeline", icon: Columns3 },
      { href: "/tasks", label: "Tasks", icon: CheckSquare },
    ],
  },
  {
    label: "Relationships",
    items: [
      { href: "/agencies", label: "Agencies", icon: Building2 },
      { href: "/companies", label: "Companies", icon: Users2 },
      { href: "/contacts", label: "Contacts", icon: Contact2 },
    ],
  },
  { label: "Planning", items: [{ href: "/forecast", label: "Forecast", icon: TrendingUp }] },
];

const SETTINGS_ITEM: NavItem = { href: "/settings", label: "Settings", icon: Settings };

function isActive(pathname: string, href: string) {
  return href === "/" ? pathname === "/" : pathname.startsWith(href);
}

function NavLink({ item, active }: { item: NavItem; active: boolean }) {
  const Icon = item.icon;
  return (
    <Link
      href={item.href}
      className={cn(
        "group relative flex items-center gap-2.5 rounded-md py-2 pl-3.5 pr-2.5 text-sm font-medium transition-colors",
        active
          ? "bg-sidebar-active text-sidebar-foreground"
          : "text-sidebar-muted-foreground hover:bg-sidebar-active/60 hover:text-sidebar-foreground"
      )}
    >
      {/* Subtle gold active indicator — the sidebar's one deliberate accent moment. */}
      <span
        className={cn(
          "absolute left-0 top-1/2 h-4 w-[3px] -translate-y-1/2 rounded-full bg-sidebar-accent transition-opacity",
          active ? "opacity-100" : "opacity-0"
        )}
      />
      <Icon className={cn("h-4 w-4 shrink-0", active ? "text-sidebar-accent" : "text-sidebar-muted-foreground group-hover:text-sidebar-foreground")} />
      <span className="truncate">{item.label}</span>
    </Link>
  );
}

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="hidden w-60 shrink-0 flex-col border-r border-sidebar-border bg-sidebar md:flex">
      <div className="flex h-16 items-center gap-2.5 border-b border-sidebar-border px-4">
        <img
          src="/assets/logo/principal-engineering-mark.png"
          alt="Principal Engineering"
          width={558}
          height={557}
          className="h-9 w-9 shrink-0 object-contain"
        />
        <div className="min-w-0 leading-tight">
          <div className="truncate text-sm font-semibold text-sidebar-foreground">Principal</div>
          <div className="truncate text-[10px] uppercase tracking-wide text-sidebar-muted-foreground">
            Opportunity Intelligence
          </div>
        </div>
      </div>

      <nav className="flex-1 space-y-5 overflow-y-auto px-3 py-4">
        {NAV_SECTIONS.map((section) => (
          <div key={section.label}>
            <div className="mb-1.5 px-3 text-[10px] font-semibold uppercase tracking-wider text-sidebar-muted-foreground/80">
              {section.label}
            </div>
            <div className="space-y-0.5">
              {section.items.map((item) => (
                <NavLink key={item.href} item={item} active={isActive(pathname, item.href)} />
              ))}
            </div>
          </div>
        ))}
      </nav>

      <div className="space-y-2 border-t border-sidebar-border px-3 py-3">
        <NavLink item={SETTINGS_ITEM} active={isActive(pathname, SETTINGS_ITEM.href)} />
        <div className="px-3 pt-1 text-[10.5px] leading-snug text-sidebar-muted-foreground">
          Find Earlier. Pursue Smarter.
          <br />
          Win More.
        </div>
      </div>
    </aside>
  );
}
