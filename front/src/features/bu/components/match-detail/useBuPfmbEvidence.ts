import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import {
  fetchBuMatchMs2Annotation,
  fetchBuMatchMs2AnnotationMatrix,
  fetchBuMatchMs2Slots,
} from "@/features/bu/api/buClient";
import type { BuMs2SlotItem } from "@/features/bu/types";
import { RT_LINK_TOLERANCE_MIN } from "@/features/bu/utils";

export function useBuPfmbEvidence({
  slug,
  matchId,
  hasPfmb,
  selectedRt,
}: {
  slug: string;
  matchId: number;
  hasPfmb: boolean;
  selectedRt: number | null;
}) {
  const slots = useQuery({
    queryKey: ["bu", slug, "matches", matchId, "ms2-slots"],
    queryFn: () => fetchBuMatchMs2Slots(slug, matchId),
    enabled: hasPfmb && Number.isFinite(matchId),
  });

  const slotData = slots.data;
  const hasSlots = Boolean(slotData?.has_pfmb && slotData.slots.length > 0);
  const { activeSlot, nearestDistance } = useMemo(() => {
    if (!hasSlots) {
      return { activeSlot: null as BuMs2SlotItem | null, nearestDistance: null as number | null };
    }
    const list = slotData!.slots;
    const apexSlot = list.find((slot) => slot.slot_index === slotData!.apex_slot) ?? list[0];
    if (selectedRt == null) return { activeSlot: apexSlot, nearestDistance: null as number | null };

    let nearest = list[0];
    let best = Infinity;
    for (const slot of list) {
      const distance = Math.abs(slot.rt_minutes - selectedRt);
      if (distance < best) {
        best = distance;
        nearest = slot;
      }
    }
    return best > RT_LINK_TOLERANCE_MIN
      ? { activeSlot: apexSlot, nearestDistance: best }
      : { activeSlot: nearest, nearestDistance: best };
  }, [hasSlots, selectedRt, slotData]);

  const activePrsm = activeSlot?.prsm_index ?? null;
  const annotation = useQuery({
    queryKey: ["bu", slug, "matches", matchId, "ms2-annotation", activePrsm],
    queryFn: () => fetchBuMatchMs2Annotation(slug, matchId, activePrsm!),
    enabled: hasPfmb && activePrsm !== null,
    placeholderData: (previousData) => previousData,
  });
  const matrix = useQuery({
    queryKey: ["bu", slug, "matches", matchId, "ms2-annotation-matrix"],
    queryFn: () => fetchBuMatchMs2AnnotationMatrix(slug, matchId),
    enabled: hasPfmb && hasSlots,
  });

  return {
    slots,
    slotData,
    hasSlots,
    activeSlot,
    activePrsm,
    nearestDistance,
    outOfTolerance:
      selectedRt != null && nearestDistance != null && nearestDistance > RT_LINK_TOLERANCE_MIN,
    annotation,
    matrix,
  };
}

export type BuPfmbEvidence = ReturnType<typeof useBuPfmbEvidence>;
