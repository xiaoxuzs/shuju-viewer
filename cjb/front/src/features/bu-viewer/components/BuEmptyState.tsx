import { Card, CardContent } from "@/components/ui/card";

export function BuEmptyState({ title, description }: { title: string; description: string }) {
  return (
    <Card>
      <CardContent className="p-8 text-center">
        <div className="text-sm font-medium text-foreground">{title}</div>
        <div className="mt-1 text-sm text-muted-foreground">{description}</div>
      </CardContent>
    </Card>
  );
}
