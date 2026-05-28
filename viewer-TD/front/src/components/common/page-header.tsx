/**
 * Page chrome: optional crumb trail, title/description, trailing actions slot.
 */
import { Link } from "react-router-dom";
import { ChevronRight, Home } from "lucide-react";
import { cn } from "@/lib/utils";

export interface Crumb {
  label: React.ReactNode;
  to?: string;
}

export function PageHeader({
  title,
  description,
  crumbs,
  actions,
  className,
}: {
  title: React.ReactNode;
  description?: React.ReactNode;
  crumbs?: Crumb[];
  actions?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("mb-8 space-y-3", className)}>
      {crumbs && crumbs.length > 0 && (
        <nav className="flex items-center gap-1 text-xs text-muted-foreground">
          <Link
            to="/"
            className="flex items-center gap-1 hover:text-foreground transition-colors"
          >
            <Home className="h-3.5 w-3.5" />
          </Link>
          {crumbs.map((c, i) => (
            <span key={i} className="flex items-center gap-1">
              <ChevronRight className="h-3.5 w-3.5 opacity-50" />
              {c.to ? (
                <Link
                  to={c.to}
                  className="hover:text-foreground transition-colors truncate max-w-[320px]"
                >
                  {c.label}
                </Link>
              ) : (
                <span className="text-foreground/80 truncate max-w-[320px]">{c.label}</span>
              )}
            </span>
          ))}
        </nav>
      )}

      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">{title}</h1>
          {description && (
            <p className="mt-1 max-w-2xl text-sm text-muted-foreground">{description}</p>
          )}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
    </div>
  );
}
