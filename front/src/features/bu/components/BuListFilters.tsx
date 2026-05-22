import { Search } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export function BuListFilters({
  search,
  onSearchChange,
  qMax,
  onQMaxChange,
  showQMax = false,
}: {
  search: string;
  onSearchChange: (value: string) => void;
  qMax?: string;
  onQMaxChange?: (value: string) => void;
  showQMax?: boolean;
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
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={() => {
          onSearchChange("");
          if (showQMax && onQMaxChange) onQMaxChange("");
        }}
      >
        Reset
      </Button>
    </div>
  );
}
