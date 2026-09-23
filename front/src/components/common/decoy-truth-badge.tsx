import { Badge } from "@/components/ui/badge";

export type DecoyTruthState = "DIRECT" | "MISSING" | "AMBIGUOUS";

export function DecoyTruthBadge({
  value,
  state,
}: {
  value: boolean | null;
  state: DecoyTruthState | undefined;
}) {
  if (state === "MISSING" || (state === "DIRECT" && value === null)) {
    return <Badge variant="secondary" data-testid="decoy-truth-badge">Unknown</Badge>;
  }
  if (state === "AMBIGUOUS") {
    return (
      <Badge
        variant="outline"
        className="border-warning/50 text-warning-foreground"
        data-testid="decoy-truth-badge"
      >
        Ambiguous
      </Badge>
    );
  }
  if (value === true) {
    return <Badge variant="outline" data-testid="decoy-truth-badge">Decoy</Badge>;
  }
  if (value === false) {
    return <Badge variant="success" data-testid="decoy-truth-badge">Target</Badge>;
  }
  return <Badge variant="secondary" data-testid="decoy-truth-badge">Unknown</Badge>;
}
