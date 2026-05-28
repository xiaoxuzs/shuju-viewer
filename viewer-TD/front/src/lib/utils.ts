/**
 * Shared helpers: `cn` merges Tailwind classes; number helpers back tables and stat cards.
 */
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** Merge classNames with clsx + tailwind-merge to avoid conflicting utilities. */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * Format arbitrary numbers: null/NaN show as em dash (`—`);
 * very small/large magnitudes use scientific notation, otherwise locale grouping/decimals.
 */
export function formatNumber(n: number | null | undefined, digits = 2): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  if (Math.abs(n) !== 0 && (Math.abs(n) < 1e-3 || Math.abs(n) >= 1e5)) {
    return n.toExponential(digits);
  }
  return n.toLocaleString(undefined, { maximumFractionDigits: digits + 2 });
}

/** Format e-/p-values: fixed two-digit scientific notation; empty values show em dash (`—`). */
export function formatEValue(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return n.toExponential(2);
}
