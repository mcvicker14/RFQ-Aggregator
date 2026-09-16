// Validated categorical palette (fixed order — never cycled by rank) from the
// dataviz skill's reference palette. Colors are assigned to a data label by a
// stable hash so the same agency/state/etc. always gets the same color across
// re-renders and filters, rather than by its position in a value-sorted array.
const CATEGORICAL_LIGHT = [
  "#2a78d6", // blue
  "#eb6834", // orange
  "#1baf7a", // aqua
  "#eda100", // yellow
  "#e87ba4", // magenta
  "#008300", // green
  "#4a3aa7", // violet
  "#e34948", // red
];

function hashString(value: string): number {
  let hash = 0;
  for (let i = 0; i < value.length; i++) {
    hash = (hash << 5) - hash + value.charCodeAt(i);
    hash |= 0;
  }
  return Math.abs(hash);
}

export function colorForLabel(label: string): string {
  return CATEGORICAL_LIGHT[hashString(label) % CATEGORICAL_LIGHT.length];
}

// Chart chrome (grid/axis) references the live theme tokens directly, so it always
// matches the rest of the UI — unlike the fixed categorical palette above, which is
// deliberately brand-independent (see its own comment).
export const CHART_GRID = "hsl(var(--border))";
export const CHART_AXIS = "hsl(var(--muted-foreground))";
export const CHART_INK_SECONDARY = "hsl(var(--foreground))";
