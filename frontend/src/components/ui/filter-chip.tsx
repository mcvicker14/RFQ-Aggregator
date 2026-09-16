"use client";

import { X } from "lucide-react";
import { cn } from "@/lib/utils";

// The "why am I here" breadcrumb for a page landed on via a Dashboard KPI drill-down —
// clearing it drops just that filter, leaving the page's own manual filters intact.
export function FilterChip({ label, onClear, className }: { label: string; onClear: () => void; className?: string }) {
  return (
    <div
      className={cn(
        "flex items-center gap-1.5 rounded-full border border-primary/30 bg-primary/5 py-1 pl-3 pr-1.5 text-xs font-medium text-primary",
        className
      )}
    >
      <span>{label}</span>
      <button
        type="button"
        onClick={onClear}
        aria-label="Clear filter"
        className="flex h-4 w-4 items-center justify-center rounded-full text-primary/70 transition-colors hover:bg-primary/15 hover:text-primary"
      >
        <X className="h-3 w-3" />
      </button>
    </div>
  );
}
