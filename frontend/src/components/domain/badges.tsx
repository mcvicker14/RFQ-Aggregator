import { Badge } from "@/components/ui/badge";
import { cn, titleCase } from "@/lib/utils";
import { FlaskConical } from "lucide-react";

export function ScoreBadge({ score, band, size = "default" }: { score: number | null; band?: string | null; size?: "default" | "lg" }) {
  if (score === null) {
    return <Badge variant="muted">Not scored</Badge>;
  }
  const resolvedBand = band ?? (score >= 75 ? "high" : score >= 50 ? "medium" : "low");
  const variant = resolvedBand === "high" ? "success" : resolvedBand === "medium" ? "warning" : "destructive";
  return (
    <Badge
      variant={variant}
      className={cn("font-semibold tabular-nums", size === "lg" && "px-3 py-1 text-base")}
    >
      {score}
      <span className="ml-0.5 font-normal opacity-70">/100</span>
    </Badge>
  );
}

export function SampleDataBadge({ className }: { className?: string }) {
  return (
    <Badge variant="accent" className={cn("gap-1 uppercase tracking-wide", className)}>
      <FlaskConical className="h-3 w-3" />
      Sample Data
    </Badge>
  );
}

export const SET_ASIDE_LABELS: Record<string, string> = {
  unrestricted: "Unrestricted",
  sdvosb: "SDVOSB Set-Aside",
  small_business: "Small Business Set-Aside",
  eight_a: "8(a) Set-Aside",
  hubzone: "HUBZone Set-Aside",
  wosb: "WOSB Set-Aside",
  edwosb: "EDWOSB Set-Aside",
  other: "Other Set-Aside",
};

export function setAsideLabel(value: string): string {
  return SET_ASIDE_LABELS[value] ?? titleCase(value);
}

export function SetAsideBadge({ value }: { value: string }) {
  const variant = value === "sdvosb" ? "accent" : value === "unrestricted" ? "muted" : "secondary";
  return <Badge variant={variant}>{SET_ASIDE_LABELS[value] ?? titleCase(value)}</Badge>;
}

export function MaturityBadge({ value }: { value: string }) {
  return <Badge variant="outline">{titleCase(value)}</Badge>;
}

export const CONTRACT_TYPE_LABELS: Record<string, string> = {
  ae_brooks_act: "A/E (Brooks Act)",
  idiq: "IDIQ",
  matoc: "MATOC",
  satoc: "SATOC",
  task_order: "Task Order",
  design_build: "Design-Build",
  construction: "Construction",
  other: "Other",
};

export function contractTypeLabel(value: string): string {
  return CONTRACT_TYPE_LABELS[value] ?? titleCase(value);
}

export function ContractTypeBadge({ value }: { value: string }) {
  return <Badge variant="outline">{contractTypeLabel(value)}</Badge>;
}

export function PriorityBadge({ value }: { value: string }) {
  const variant = value === "urgent" ? "destructive" : value === "high" ? "warning" : value === "medium" ? "secondary" : "muted";
  return <Badge variant={variant}>{titleCase(value)}</Badge>;
}

export function TaskStatusBadge({ value }: { value: string }) {
  const variant = value === "completed" ? "success" : value === "cancelled" ? "muted" : value === "in_progress" ? "accent" : "outline";
  return <Badge variant={variant}>{titleCase(value)}</Badge>;
}

export function GoNoGoBadge({ value }: { value: string | null }) {
  if (!value) return <Badge variant="muted">Not decided</Badge>;
  const variant = value === "go" ? "success" : value === "conditional_go" ? "warning" : "destructive";
  return <Badge variant={variant}>{titleCase(value)}</Badge>;
}

export const INTELLIGENCE_CATEGORY_LABELS: Record<string, string> = {
  live_opportunity: "Live Opportunity",
  pre_solicitation: "Pre-Solicitation",
  early_signal: "Early Signal",
  award_intelligence: "Award Intelligence",
};

export function IntelligenceCategoryBadge({ value }: { value: string }) {
  const variant = value === "live_opportunity" ? "success" : value === "pre_solicitation" ? "accent" : value === "early_signal" ? "warning" : "secondary";
  return <Badge variant={variant}>{INTELLIGENCE_CATEGORY_LABELS[value] ?? titleCase(value)}</Badge>;
}
