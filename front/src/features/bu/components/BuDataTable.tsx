import { Link } from "react-router-dom";
import type { ReactNode } from "react";

import { PageLoading } from "@/components/common/page-loading";
import { Card, CardContent } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { BuEmptyState } from "@/features/bu/components/BuEmptyState";

export interface BuColumn<T> {
  key: string;
  header: string;
  className?: string;
  render: (row: T) => ReactNode;
}

export function BuDataTable<T extends { id: number }>({
  columns,
  rows,
  isLoading,
  emptyTitle,
  emptyDescription,
  rowHref,
}: {
  columns: BuColumn<T>[];
  rows: T[];
  isLoading: boolean;
  emptyTitle: string;
  emptyDescription: string;
  rowHref?: (row: T) => string;
}) {
  if (isLoading) {
    return (
      <Card>
        <CardContent className="p-0">
          <PageLoading className="min-h-48" />
        </CardContent>
      </Card>
    );
  }

  if (rows.length === 0) {
    return <BuEmptyState title={emptyTitle} description={emptyDescription} />;
  }

  return (
    <Card>
      <CardContent className="p-0">
        <Table>
          <TableHeader>
            <TableRow>
              {columns.map((column) => (
                <TableHead key={column.key} className={column.className}>
                  {column.header}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row) => {
              const href = rowHref?.(row);
              return (
                <TableRow key={row.id} className={href ? "cursor-pointer" : undefined}>
                  {columns.map((column, index) => (
                    <TableCell key={column.key} className={column.className}>
                      {index === 0 && href ? (
                        <Link to={href} className="font-medium text-foreground hover:text-primary">
                          {column.render(row)}
                        </Link>
                      ) : (
                        column.render(row)
                      )}
                    </TableCell>
                  ))}
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}
