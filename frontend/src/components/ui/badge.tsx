import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium whitespace-nowrap",
  {
    variants: {
      variant: {
        default: "border-transparent bg-primary text-primary-foreground",
        secondary: "border-transparent bg-secondary text-secondary-foreground",
        outline: "border-border text-foreground",
        // Soft tint + a whisper of matching-color border, rather than a flat fill —
        // restrained enough that only the highest-priority items need to stand out.
        success: "border-success/15 bg-success/10 text-success",
        warning: "border-warning/15 bg-warning/10 text-warning",
        destructive: "border-destructive/15 bg-destructive/10 text-destructive",
        // Gold — reserved for the specific "this is the important one" signal, not a
        // general-purpose status color (see components/domain/badges.tsx for where).
        accent: "border-accent/25 bg-accent/10 text-accent-foreground",
        muted: "border-transparent bg-muted text-muted-foreground",
      },
    },
    defaultVariants: { variant: "default" },
  }
);

export interface BadgeProps extends React.HTMLAttributes<HTMLDivElement>, VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />;
}
