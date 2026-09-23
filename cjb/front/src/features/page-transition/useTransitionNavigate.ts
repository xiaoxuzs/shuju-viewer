import { useCallback } from "react";
import {
  resolvePath,
  useLocation,
  useNavigate,
  type NavigateOptions,
  type To,
} from "react-router-dom";

import { usePageTransition } from "./pageTransitionContext";

export function useTransitionNavigate() {
  const navigate = useNavigate();
  const location = useLocation();
  const { beginRouteTransition } = usePageTransition();

  return useCallback((to: To, options?: NavigateOptions) => {
    const resolved = resolvePath(to, location.pathname);
    if (resolved.pathname !== location.pathname) beginRouteTransition(resolved.pathname);
    navigate(to, options);
  }, [beginRouteTransition, location.pathname, navigate]);
}
