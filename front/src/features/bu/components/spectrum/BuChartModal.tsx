import { useEffect, type ReactNode } from "react";
import { X } from "lucide-react";

export function BuChartModal({
  title,
  subtitle,
  onClose,
  children,
  actions,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  onClose: () => void;
  children: ReactNode;
  actions?: ReactNode;
}) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/55 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      onClick={onClose}
    >
      <div
        className="relative flex h-[88vh] w-[94vw] max-w-[1480px] flex-col rounded-xl border bg-card text-card-foreground shadow-xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4 border-b border-border p-4">
          <div className="min-w-0">
            <div className="truncate text-base font-semibold">{title}</div>
            {subtitle && <div className="mt-0.5 truncate text-xs text-muted-foreground">{subtitle}</div>}
          </div>
          <div className="flex items-center gap-2">
            {actions}
            <button
              type="button"
              aria-label="close"
              className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-border bg-background text-muted-foreground hover:bg-accent hover:text-foreground"
              onClick={onClose}
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>
        <div className="flex-1 overflow-hidden p-4">{children}</div>
      </div>
    </div>
  );
}
