import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";

export interface TransitionBatch {
  id: number;
  active: boolean;
}

export interface PageTransitionContextValue extends TransitionBatch {
  beginManualTransition: () => number;
  beginRouteTransition: (pathname: string) => number;
  completeTransition: (batchId: number) => void;
}

export const PageTransitionContext = createContext<PageTransitionContextValue | null>(null);

export function usePageTransition() {
  const context = useContext(PageTransitionContext);
  if (!context) throw new Error("usePageTransition must be used within PageTransitionProvider");
  return context;
}

export function usePageTransitionReady(ready: boolean) {
  const { active, id, completeTransition } = usePageTransition();

  useEffect(() => {
    if (!active || !ready) return;
    let firstFrame = 0;
    let secondFrame = 0;
    firstFrame = window.requestAnimationFrame(() => {
      secondFrame = window.requestAnimationFrame(() => completeTransition(id));
    });
    return () => {
      window.cancelAnimationFrame(firstFrame);
      window.cancelAnimationFrame(secondFrame);
    };
  }, [active, completeTransition, id, ready]);
}

export function useTransitionSignal(key: string | number | null) {
  const keyRef = useRef(key);
  keyRef.current = key;
  const [signal, setSignal] = useState<{ key: string | number | null; ready: boolean }>({
    key,
    ready: false,
  });
  const ready = Object.is(signal.key, key) && signal.ready;
  const markReady = useCallback(() => {
    if (!Object.is(keyRef.current, key)) return;
    setSignal((current) => (
      Object.is(current.key, key) && current.ready ? current : { key, ready: true }
    ));
  }, [key]);
  return [ready, markReady] as const;
}
