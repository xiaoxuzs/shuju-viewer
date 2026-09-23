import { Loader2 } from "lucide-react";

import { cn } from "@/lib/utils";

export interface PageLoadingProps {
  text?: string;
  fullscreen?: boolean;
  overlay?: boolean;
  className?: string;
}

export function PageLoading({
  text,
  fullscreen = false,
  overlay = false,
  className,
}: PageLoadingProps) {
  return (
    <div
      className={cn(
        "flex min-h-64 w-full items-center justify-center",
        fullscreen && "fixed inset-0 z-50 min-h-0 bg-background/90 backdrop-blur-sm",
        overlay && !fullscreen && "absolute inset-0 z-30 min-h-0 bg-background/75 backdrop-blur-[1px]",
        className,
      )}
      role="status"
      aria-label={text || "Loading"}
      aria-live="polite"
      aria-busy="true"
    >
      <div className="flex flex-col items-center gap-3">
        <Loader2 className="h-7 w-7 animate-spin text-primary" aria-hidden="true" />
        {text ? <p className="text-sm text-muted-foreground">{text}</p> : null}
      </div>
    </div>
  );
}
