/**
 * 统计卡片：小标题 + 大号数值，可选次要说明行。
 */
import { cn } from "@/lib/utils";

export function Stat({
  label,
  value,
  hint,
  className,
}: {
  label: React.ReactNode;
  value: React.ReactNode;
  hint?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "rounded-xl border border-border/50 bg-card/50 p-4 backdrop-blur transition-colors hover:border-border",
        className,
      )}
    >
      <div className="text-xs uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className="mt-1 text-2xl font-semibold tracking-tight">{value}</div>
      {hint && <div className="mt-1 text-xs text-muted-foreground">{hint}</div>}
    </div>
  );
}
