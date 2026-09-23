/**
 * 通用工具：`cn` 合并 Tailwind 类名；数值格式化供表格与统计卡片使用。
 */
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** 合并 className（clsx + tailwind-merge），避免样式冲突。 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * 格式化一般数值：空或 NaN 显示为「—」；
 * 绝对值过小或过大时用科学计数法，否则用本地化小数/千分位。
 */
export function formatNumber(n: number | null | undefined, digits = 2): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  if (Math.abs(n) !== 0 && (Math.abs(n) < 1e-3 || Math.abs(n) >= 1e5)) {
    return n.toExponential(digits);
  }
  return n.toLocaleString(undefined, { maximumFractionDigits: digits + 2 });
}

/** 格式化 e-value / p-value 等：固定两位小数的科学计数法；空显示「—」。 */
export function formatEValue(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return n.toExponential(2);
}
