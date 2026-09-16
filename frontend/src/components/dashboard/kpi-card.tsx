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
}: {
  label: string;
  value: string | number;
  icon?: LucideIcon;
  tone?: "default" | "accent" | "warning" | "success" | "destructive";
  className?: string;
}) {
  return (
    <Card className={cn("p-4", className)}>
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
}
