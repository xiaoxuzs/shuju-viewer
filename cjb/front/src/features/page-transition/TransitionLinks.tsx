import { useCallback, type MouseEvent } from "react";
import {
  Link,
  NavLink,
  useLocation,
  useResolvedPath,
  type LinkProps,
  type NavLinkProps,
} from "react-router-dom";

import { usePageTransition } from "./pageTransitionContext";

export function TransitionLink({ onClick, target, to, ...props }: LinkProps) {
  const location = useLocation();
  const resolved = useResolvedPath(to);
  const { beginRouteTransition } = usePageTransition();
  const handleClick = useCallback((event: MouseEvent<HTMLAnchorElement>) => {
    onClick?.(event);
    if (
      event.defaultPrevented
      || event.button !== 0
      || target === "_blank"
      || event.metaKey
      || event.altKey
      || event.ctrlKey
      || event.shiftKey
      || resolved.pathname === location.pathname
    ) return;
    beginRouteTransition(resolved.pathname);
  }, [beginRouteTransition, location.pathname, onClick, resolved.pathname, target]);

  return <Link {...props} to={to} target={target} onClick={handleClick} />;
}

export function TransitionNavLink({ onClick, target, to, ...props }: NavLinkProps) {
  const location = useLocation();
  const resolved = useResolvedPath(to);
  const { beginRouteTransition } = usePageTransition();
  const handleClick = useCallback((event: MouseEvent<HTMLAnchorElement>) => {
    onClick?.(event);
    if (
      event.defaultPrevented
      || event.button !== 0
      || target === "_blank"
      || event.metaKey
      || event.altKey
      || event.ctrlKey
      || event.shiftKey
      || resolved.pathname === location.pathname
    ) return;
    beginRouteTransition(resolved.pathname);
  }, [beginRouteTransition, location.pathname, onClick, resolved.pathname, target]);

  return <NavLink {...props} to={to} target={target} onClick={handleClick} />;
}
