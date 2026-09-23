export function EvidenceJumpControls({
  onJumpToMs2,
  onJumpToPfmb,
}: {
  onJumpToMs2: () => void;
  onJumpToPfmb: () => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs">
      <button
        type="button"
        onClick={onJumpToMs2}
        className="rounded-md border border-border bg-background px-2.5 py-1.5 font-medium text-muted-foreground transition-colors hover:text-foreground"
        data-testid="jump-to-ms2-spectrum"
      >
        View updated MS2 spectrum
      </button>
      <button
        type="button"
        onClick={onJumpToPfmb}
        className="rounded-md border border-border bg-background px-2.5 py-1.5 font-medium text-muted-foreground transition-colors hover:text-foreground"
        data-testid="jump-to-pfmb-heatmap"
      >
        Back to Fragment Match heatmap
      </button>
    </div>
  );
}
