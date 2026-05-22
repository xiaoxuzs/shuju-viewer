import { Card, CardContent } from "@/components/ui/card";

export function BuComingSoonPage({ title = "即将支持" }: { title?: string }) {
  return (
    <Card>
      <CardContent className="p-8 text-center">
        <div className="text-base font-medium text-foreground">{title}</div>
        <div className="mt-2 text-sm text-muted-foreground">
          This Bottom-Up view is intentionally not mounted in PR-4.
        </div>
      </CardContent>
    </Card>
  );
}
