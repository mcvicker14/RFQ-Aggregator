import Link from "next/link";
import { cn } from "@/lib/utils";
import { Card } from "@/components/ui/card";
import type { LucideIcon } from "lucide-react";

// Same restrained tone system as components/domain/badges.tsx — the icon chip carries
// the color signal, the value itself always stays a strongly-readable neutral so large
// numbers are never harder to read than they need to be.
const TONE_CHIP: Record<string, string> = {
  default: "bg-secondary text-muted-foreground",
  accent: "bg-accent/15 text-accent-foreground",
  warning: "bg-warning/12 text-warning",
  success: "bg-success/12 text-success",
  destructive: "bg-destructive/12 text-destructive",
};

export function KpiCard({
  label,
  value,
  icon: Icon,
  tone = "default",
  className,
  href,
}: {
  label: string;
  value: string | number;
  icon?: LucideIcon;
  tone?: "default" | "accent" | "warning" | "success" | "destructive";
  className?: string;
  // When set, the whole card becomes a link to the filtered record set this KPI
  // represents (see app/page.tsx's href-builders) — always the same shared
  // filter/query definition the count itself was computed from, never a
  // separately-maintained approximation of it.
  href?: string;
}) {
  const card = (
    <Card
      className={cn(
        "p-4",
        href && "cursor-pointer transition-shadow hover:border-primary/30 hover:shadow-md",
        className
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium text-muted-foreground">{label}</span>
        {Icon && (
          <span className={cn("flex h-7 w-7 shrink-0 items-center justify-center rounded-md", TONE_CHIP[tone])}>
            <Icon className="h-3.5 w-3.5" />
          </span>
        )}
      </div>
      <div className="mt-2.5 text-2xl font-semibold tabular-nums text-foreground">{value}</div>
    </Card>
  );
  return href ? (
    <Link href={href} className="block">
      {card}
    </Link>
  ) : (
    card
  );
}
