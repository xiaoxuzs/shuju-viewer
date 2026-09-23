export type FollowPfmbSlotControlsProps = {
  followPfmbSlot: boolean;
  onFollowChange: (next: boolean) => void;
  onLockMs2Scan: () => void;
};

export function FollowPfmbSlotControls({
  followPfmbSlot,
  onFollowChange,
  onLockMs2Scan,
}: FollowPfmbSlotControlsProps) {
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs">
      <label className="inline-flex items-center gap-2 rounded-md border border-border bg-background px-2.5 py-1.5 text-muted-foreground">
        <input
          type="checkbox"
          checked={followPfmbSlot}
          onChange={(event) => onFollowChange(event.currentTarget.checked)}
          className="h-4 w-4 accent-primary"
          data-testid="follow-pfmb-slot-toggle"
        />
        <span className="font-medium text-foreground">Follow Fragment Match slot</span>
      </label>
      <button
        type="button"
        onClick={onLockMs2Scan}
        className="rounded-md border border-border bg-background px-2.5 py-1.5 font-medium text-muted-foreground transition-colors hover:text-foreground"
        data-testid="lock-ms2-scan-button"
      >
        Lock MS2 scan
      </button>
    </div>
  );
}
