import { Search } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { BuRunSummary } from "@/features/bu/types";
import { formatCount } from "@/features/bu/utils";

export function BuListFilters({
  search,
  onSearchChange,
  qMax,
  onQMaxChange,
  showQMax = false,
  hideDecoy,
  onHideDecoyChange,
  showDecoyToggle = false,
  runs = [],
  runId,
  onRunIdChange,
  showRunFilter = false,
  onReset,
}: {
  search: string;
  onSearchChange: (value: string) => void;
  qMax?: string;
  onQMaxChange?: (value: string) => void;
  showQMax?: boolean;
  hideDecoy?: boolean;
  onHideDecoyChange?: (value: boolean) => void;
  showDecoyToggle?: boolean;
  runs?: BuRunSummary[];
  runId?: string;
  onRunIdChange?: (value: string) => void;
  showRunFilter?: boolean;
  onReset?: () => void;
}) {
  return (
    <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
      <div className="relative min-w-0 sm:w-80">
        <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
        <Input
          className="pl-8"
          placeholder="Search"
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
        />
      </div>
      {showQMax && onQMaxChange && (
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-muted-foreground">Q max</span>
          <Input
            className="w-28 font-mono"
            type="number"
            min="0"
            step="0.001"
            value={qMax ?? ""}
            onChange={(e) => onQMaxChange(e.target.value)}
          />
        </div>
      )}
      {showRunFilter && onRunIdChange && (
        <label className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
          Run
          <select
            value={runId ?? ""}
            onChange={(e) => onRunIdChange(e.target.value)}
            className="max-w-[280px] rounded-md border border-input bg-background px-2 py-2 text-xs text-foreground"
          >
            <option value="">All runs</option>
            {runs.map((run) => (
              <option key={run.run_id} value={run.run_id}>
                {run.raw_format ?? "unknown"} - {run.file_name} - {formatCount(run.match_count)}
              </option>
            ))}
          </select>
        </label>
      )}
      {showDecoyToggle && onHideDecoyChange && (
        <label className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
          <input
            type="checkbox"
            checked={hideDecoy ?? true}
            onChange={(e) => onHideDecoyChange(e.target.checked)}
            className="h-4 w-4 rounded border-border"
          />
          Hide decoy
        </label>
      )}
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={() => {
          if (onReset) {
            onReset();
            return;
          }
          onSearchChange("");
          if (showQMax && onQMaxChange) onQMaxChange("");
          if (showRunFilter && onRunIdChange) onRunIdChange("");
          if (showDecoyToggle && onHideDecoyChange) onHideDecoyChange(true);
        }}
      >
        Reset
      </Button>
    </div>
  );
}
