/**
 * 简单分页控件：展示当前区间与总条数，首尾/上一页/下一页按钮。
 */
import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight } from "lucide-react";
import { Button } from "@/components/ui/button";

export function Pagination({
  page,
  pageSize,
  total,
  onPageChange,
}: {
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
}) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(total, page * pageSize);

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 text-xs text-muted-foreground">
      <div>
        {total === 0 ? (
          "No rows"
        ) : (
          <>
            Showing <span className="font-medium text-foreground">{from.toLocaleString()}</span>–
            <span className="font-medium text-foreground">{to.toLocaleString()}</span> of{" "}
            <span className="font-medium text-foreground">{total.toLocaleString()}</span>
          </>
        )}
      </div>
      <div className="flex items-center gap-1">
        <Button
          variant="outline"
          size="icon"
          disabled={page <= 1}
          onClick={() => onPageChange(1)}
          className="h-8 w-8"
        >
          <ChevronsLeft className="h-4 w-4" />
        </Button>
        <Button
          variant="outline"
          size="icon"
          disabled={page <= 1}
          onClick={() => onPageChange(page - 1)}
          className="h-8 w-8"
        >
          <ChevronLeft className="h-4 w-4" />
        </Button>
        <span className="px-2 font-medium text-foreground">
          {page} / {totalPages}
        </span>
        <Button
          variant="outline"
          size="icon"
          disabled={page >= totalPages}
          onClick={() => onPageChange(page + 1)}
          className="h-8 w-8"
        >
          <ChevronRight className="h-4 w-4" />
        </Button>
        <Button
          variant="outline"
          size="icon"
          disabled={page >= totalPages}
          onClick={() => onPageChange(totalPages)}
          className="h-8 w-8"
        >
          <ChevronsRight className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}
