import { AlertTriangle, Database, Loader2 } from "lucide-react";

import { cn } from "@/lib/utils";

export type PlotStatusKind =
  | "loading"
  | "empty"
  | "no_signal"
  | "unsupported"
  | "derived_missing"
  | "derived_stale"
  | "not_found"
  | "error";

const DEFAULT_TEXT: Record<PlotStatusKind, { title: string; message?: string }> = {
  loading: { title: "Loading chart..." },
  empty: { title: "No data available." },
  no_signal: { title: "No signal in the selected range." },
  unsupported: { title: "This raw format is not supported for this chart." },
  derived_missing: {
    title: "Derived data is not ready.",
    message: "Run the backfill command on the server, then refresh this page.",
  },
  derived_stale: {
    title: "Derived data is stale.",
    message: "Run the backfill command on the server, then refresh this page.",
  },
  not_found: { title: "The requested data could not be found." },
  error: { title: "Something went wrong while loading this chart." },
};

export function PlotStatus({
  kind,
  title,
  message,
  command,
  className,
}: {
  kind: PlotStatusKind;
  title?: string;
  message?: string;
  command?: string | null;
  className?: string;
}) {
  const text = DEFAULT_TEXT[kind];
  const isError = kind === "error";
  const isLoading = kind === "loading";
  const Icon = isLoading
    ? Loader2
    : kind === "derived_missing" || kind === "derived_stale"
      ? Database
      : AlertTriangle;

  return (
    <div
      className={cn(
        "flex min-h-56 w-full items-center justify-center rounded-md border border-dashed px-5 py-8 text-center",
        isError
          ? "border-destructive/40 bg-destructive/5 text-destructive"
          : "border-border/70 bg-muted/15",
        className,
      )}
      role={isError ? "alert" : "status"}
      aria-live="polite"
      aria-busy={isLoading || undefined}
    >
      <div className="flex max-w-xl flex-col items-center gap-2">
        <Icon
          className={cn(
            "h-5 w-5",
            isLoading && "animate-spin text-primary",
            !isLoading && !isError && "text-muted-foreground",
          )}
          aria-hidden="true"
        />
        <p className="text-sm font-medium">{title ?? text.title}</p>
        {(message ?? text.message) && (
          <p className="text-xs text-muted-foreground">{message ?? text.message}</p>
        )}
        {command && (
          <code className="mt-1 max-w-full overflow-x-auto rounded bg-muted px-2 py-1 text-left text-xs text-foreground">
            {command}
          </code>
        )}
      </div>
    </div>
  );
}
