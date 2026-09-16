import { Badge } from "@/components/ui/badge";
import { cn, titleCase } from "@/lib/utils";
import { FlaskConical } from "lucide-react";

// Badge tone system, used consistently across every domain badge in this file:
//   success  — favorable / live / positive status
//   warning  — needs attention / in progress / moderate confidence
//   destructive — negative / expired / rejected
//   accent (gold) — reserved for the single most important signal in a given context
//                    (see each component below for exactly where and why)
//   secondary / outline / muted — everything else; the default, most common tone

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

// Relevance tier badges (SAM Relevance Score, Grant Engineering Relevance Score): the
// single place score *meaning*, not just a color, is standardized. Named so a reader
// never has to mentally map "81" to a tier — the tier name is printed on the badge.
// Gold is used exactly once here, for the top tier only ("key score accents" — the
// spec's own words) — Relevant/Possible Match/Low Relevance deliberately are not gold,
// so the top tier still reads as genuinely special rather than one of several gold badges.
const RELEVANCE_TIER_LABELS: Record<string, string> = {
  highly_relevant: "Highly Relevant",
  relevant: "Relevant",
  possible_match: "Possible Match",
  high_value_signal: "High-Value Signal",
  relevant_signal: "Relevant Signal",
  possible_signal: "Possible Signal",
  low_relevance: "Low Relevance",
  unscored: "Not Scored",
};

const RELEVANCE_TIER_VARIANT: Record<string, "accent" | "success" | "warning" | "muted"> = {
  highly_relevant: "accent",
  high_value_signal: "accent",
  relevant: "success",
  relevant_signal: "success",
  possible_match: "warning",
  possible_signal: "warning",
  low_relevance: "muted",
  unscored: "muted",
};

export function RelevanceTierBadge({ tier, score }: { tier: string; score: number | null }) {
  const variant = RELEVANCE_TIER_VARIANT[tier] ?? "muted";
  const label = RELEVANCE_TIER_LABELS[tier] ?? titleCase(tier);
  return (
    <Badge variant={variant} className="gap-1 font-medium">
      {label}
      {score !== null && <span className="font-semibold tabular-nums opacity-90">· {score}</span>}
    </Badge>
  );
}

export function SampleDataBadge({ className }: { className?: string }) {
  // Informational caveat, not a positive highlight — muted, not gold, so it never
  // competes with the badges that are actually signaling something important.
  return (
    <Badge variant="outline" className={cn("gap-1 uppercase tracking-wide text-muted-foreground", className)}>
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
  // SDVOSB is Principal's own set-aside status — the one set-aside genuinely worth
  // flagging as a differentiator; everything else is a neutral descriptor.
  const variant = value === "sdvosb" ? "success" : value === "unrestricted" ? "muted" : "secondary";
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
  const variant = value === "completed" ? "success" : value === "cancelled" ? "muted" : value === "in_progress" ? "warning" : "outline";
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

// Pre-Solicitation is the one deliberately-gold category — it's the earliest point
// Principal can meaningfully position on an opportunity (see docs/PHASE2_ARCHITECTURE.md),
// worth visually standing out from the other three, which use the ordinary tone system.
export function IntelligenceCategoryBadge({ value }: { value: string }) {
  const variant =
    value === "live_opportunity" ? "success" : value === "pre_solicitation" ? "accent" : value === "early_signal" ? "warning" : "secondary";
  return <Badge variant={variant}>{INTELLIGENCE_CATEGORY_LABELS[value] ?? titleCase(value)}</Badge>;
}
