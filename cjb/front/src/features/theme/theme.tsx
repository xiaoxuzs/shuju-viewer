import {
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import {
  ThemeContext,
  THEME_STORAGE_KEY,
  type ResolvedTheme,
  type ThemeMode,
} from "@/features/theme/themeContext";

const DARK_SCHEME_QUERY = "(prefers-color-scheme: dark)";

function isThemeMode(value: string | null): value is ThemeMode {
  return value === "light" || value === "dark" || value === "system";
}

function systemTheme(): ResolvedTheme {
  return window.matchMedia(DARK_SCHEME_QUERY).matches ? "dark" : "light";
}

function readInitialMode(): ThemeMode {
  if (typeof window === "undefined") return "system";
  let stored: string | null = null;
  try {
    stored = window.localStorage.getItem(THEME_STORAGE_KEY);
  } catch {
    stored = null;
  }
  if (isThemeMode(stored)) return stored;
  const bootMode = document.documentElement.dataset.theme ?? null;
  return isThemeMode(bootMode) ? bootMode : "system";
}

function resolveTheme(mode: ThemeMode): ResolvedTheme {
  return mode === "system" ? systemTheme() : mode;
}

function applyTheme(mode: ThemeMode, resolvedTheme: ResolvedTheme) {
  const root = document.documentElement;
  root.classList.toggle("dark", resolvedTheme === "dark");
  root.dataset.theme = mode;
  root.dataset.resolvedTheme = resolvedTheme;
  root.style.colorScheme = resolvedTheme;
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<ThemeMode>(readInitialMode);
  const [resolvedTheme, setResolvedTheme] = useState<ResolvedTheme>(() => resolveTheme(readInitialMode()));

  useEffect(() => {
    const media = window.matchMedia(DARK_SCHEME_QUERY);
    const syncTheme = () => {
      const resolved = mode === "system" ? (media.matches ? "dark" : "light") : mode;
      setResolvedTheme(resolved);
      applyTheme(mode, resolved);
    };

    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, mode);
    } catch {
      // Theme selection still applies for this page when storage is unavailable.
    }
    syncTheme();
    if (mode !== "system") return;

    media.addEventListener("change", syncTheme);
    return () => media.removeEventListener("change", syncTheme);
  }, [mode]);

  const value = useMemo(() => ({ mode, resolvedTheme, setMode }), [mode, resolvedTheme]);
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}
