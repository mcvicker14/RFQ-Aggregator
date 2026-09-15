import { cn } from "@/lib/utils";
import { Card } from "@/components/ui/card";
import type { LucideIcon } from "lucide-react";

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
  const toneClass = {
    default: "text-foreground",
    accent: "text-accent-foreground",
    warning: "text-warning",
    success: "text-success",
    destructive: "text-destructive",
  }[tone];

  return (
    <Card className={cn("p-4", className)}>
      <div className="flex items-start justify-between gap-2">
        <span className="text-xs font-medium text-muted-foreground">{label}</span>
        {Icon && <Icon className="h-3.5 w-3.5 text-muted-foreground" />}
      </div>
      <div className={cn("mt-2 text-2xl font-semibold tabular-nums", toneClass)}>{value}</div>
    </Card>
  );
}
