import Link from "next/link";
import { cn } from "@/lib/utils";

// A deliberately smaller, denser building block than KpiCard — used for the
// Dashboard's lower-priority KPI tiers so de-emphasis reads as an actual information
// hierarchy (grouped, compact chips) rather than just "the same card, shrunk."
const VALUE_TONE: Record<string, string> = {
  default: "text-foreground",
  warning: "text-warning",
  success: "text-success",
  destructive: "text-destructive",
};

export function CompactStat({
  label,
  value,
  href,
  tone = "default",
}: {
  label: string;
  value: string | number;
  href?: string;
  tone?: "default" | "warning" | "success" | "destructive";
}) {
  const content = (
    <div
      className={cn(
        "flex flex-col gap-0.5 rounded-md border border-border bg-card px-3 py-2",
        href && "cursor-pointer transition-colors hover:border-primary/30 hover:bg-secondary/40"
      )}
    >
      <span className="whitespace-nowrap text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </span>
      <span className={cn("text-sm font-semibold tabular-nums", VALUE_TONE[tone])}>{value}</span>
    </div>
  );
  return href ? (
    <Link href={href} className="block">
      {content}
    </Link>
  ) : (
    content
  );
}
