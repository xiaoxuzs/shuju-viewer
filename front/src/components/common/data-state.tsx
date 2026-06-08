import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

interface DataStateProps {
  message?: string;
  compact?: boolean;
  className?: string;
}

export function DataLoadError({
  message = "Failed to load data.",
  compact = false,
  className,
}: DataStateProps) {
  if (compact) {
    return (
      <div
        className={cn(
          "rounded-md border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive",
          className,
        )}
        role="alert"
      >
        {message}
      </div>
    );
  }

  return (
    <Card className={cn("border-destructive/40 bg-destructive/5", className)}>
      <CardContent
        className="p-6 text-sm text-destructive"
        role="alert"
      >
        {message}
      </CardContent>
    </Card>
  );
}

export function DataEmptyState({
  message = "No data available.",
  compact = false,
  className,
}: DataStateProps) {
  const content = (
    <div
      className={cn("p-6 text-center text-sm text-muted-foreground", className)}
      role="status"
    >
      {message}
    </div>
  );

  if (compact) return content;

  return (
    <Card>
      <CardContent className="p-0">{content}</CardContent>
    </Card>
  );
}
