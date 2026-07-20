import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useLocation } from "react-router-dom";

import {
  PageTransitionContext,
  type PageTransitionContextValue,
  type TransitionBatch,
} from "./pageTransitionContext";

const TRANSITION_SAFETY_MS = 45_000;

export function PageTransitionProvider({ children }: { children: ReactNode }) {
  const location = useLocation();
  const counterRef = useRef(1);
  const batchRef = useRef<TransitionBatch>({ id: 1, active: true });
  const pendingRouteRef = useRef<string | null>(null);
  const pathnameRef = useRef(location.pathname);
  const safetyTimerRef = useRef<number | null>(null);
  const [batch, setBatch] = useState<TransitionBatch>(batchRef.current);

  const clearSafetyTimer = useCallback(() => {
    if (safetyTimerRef.current != null) {
      window.clearTimeout(safetyTimerRef.current);
      safetyTimerRef.current = null;
    }
  }, []);

  const updateBatch = useCallback((next: TransitionBatch) => {
    batchRef.current = next;
    setBatch(next);
  }, []);

  const armSafetyTimer = useCallback((batchId: number) => {
    clearSafetyTimer();
    safetyTimerRef.current = window.setTimeout(() => {
      const current = batchRef.current;
      if (current.id !== batchId || !current.active) return;
      pendingRouteRef.current = null;
      updateBatch({ ...current, active: false });
    }, TRANSITION_SAFETY_MS);
  }, [clearSafetyTimer, updateBatch]);

  const beginTransition = useCallback((pendingPathname: string | null) => {
    const next: TransitionBatch = { id: counterRef.current + 1, active: true };
    counterRef.current = next.id;
    pendingRouteRef.current = pendingPathname;
    updateBatch(next);
    armSafetyTimer(next.id);
    return next.id;
  }, [armSafetyTimer, updateBatch]);

  const beginManualTransition = useCallback(
    () => beginTransition(null),
    [beginTransition],
  );

  const beginRouteTransition = useCallback(
    (pathname: string) => beginTransition(pathname),
    [beginTransition],
  );

  const completeTransition = useCallback((batchId: number) => {
    const current = batchRef.current;
    if (current.id !== batchId || !current.active || pendingRouteRef.current != null) return;
    clearSafetyTimer();
    updateBatch({ ...current, active: false });
  }, [clearSafetyTimer, updateBatch]);

  useLayoutEffect(() => {
    if (pathnameRef.current === location.pathname) return;
    pathnameRef.current = location.pathname;

    if (pendingRouteRef.current === location.pathname && batchRef.current.active) {
      pendingRouteRef.current = null;
      return;
    }

    beginTransition(null);
  }, [beginTransition, location.pathname]);

  useEffect(() => {
    armSafetyTimer(batchRef.current.id);
    return clearSafetyTimer;
  }, [armSafetyTimer, clearSafetyTimer]);

  const value = useMemo<PageTransitionContextValue>(() => ({
    ...batch,
    beginManualTransition,
    beginRouteTransition,
    completeTransition,
  }), [batch, beginManualTransition, beginRouteTransition, completeTransition]);

  return (
    <PageTransitionContext.Provider value={value}>
      {children}
      <div
        aria-hidden="true"
        data-batch-id={batch.id}
        data-state={batch.active ? "active" : "idle"}
        data-testid="page-transition-mask"
        className={`fixed inset-0 z-[2147483647] bg-background transition-opacity duration-100 ease-out ${
          batch.active ? "pointer-events-auto opacity-100" : "pointer-events-none opacity-0"
        }`}
      />
    </PageTransitionContext.Provider>
  );
}
