import { UNIMOD_LABELS } from "@/features/bu-viewer/generated/unimodLabels.generated";

export function getUnimodDisplayName(
  id: string | number | null | undefined,
): string | null {
  if (id == null) return null;
  const key = String(id);
  return UNIMOD_LABELS[key] ?? null;
}

// Replaces `UniMod:<id>` tokens (case-insensitive) with their English label.
// Unknown ids and bracket structure are preserved unchanged.
export function formatModifiedSequenceForDisplay(value?: string | null): string {
  if (!value) return "";
  return value.replace(/UniMod:(\d+)/gi, (match, id) => {
    return UNIMOD_LABELS[id] ?? match;
  });
}
