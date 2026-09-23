export function EvidenceUpdateNotice({ message }: { message?: string | null }) {
  if (!message) return null;
  return (
    <div
      className="rounded-md border border-primary/30 bg-primary/5 px-3 py-2 text-xs font-medium text-foreground"
      role="status"
      data-testid="evidence-update-notice"
    >
      {message}
    </div>
  );
}
