// Light/dark theme. The system preference applies until the toggle is used; the choice lives in
// memory only (never browser storage), so a reload returns to the system preference.
import { useSyncExternalStore } from "react";

export type Theme = "light" | "dark";

const DARK_QUERY = "(prefers-color-scheme: dark)";
let chosen: Theme | null = null;
const listeners = new Set<() => void>();

function systemTheme(): Theme {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return "light";
  return window.matchMedia(DARK_QUERY).matches ? "dark" : "light";
}

function current(): Theme {
  return chosen ?? systemTheme();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  const media =
    typeof window !== "undefined" && typeof window.matchMedia === "function"
      ? window.matchMedia(DARK_QUERY)
      : null;
  media?.addEventListener("change", listener);
  return () => {
    listeners.delete(listener);
    media?.removeEventListener("change", listener);
  };
}

export function setTheme(theme: Theme): void {
  chosen = theme;
  document.documentElement.dataset.theme = theme;
  listeners.forEach((listener) => {
    listener();
  });
}

export function useTheme(): { theme: Theme; toggle: () => void } {
  const theme = useSyncExternalStore<Theme>(subscribe, current, () => "light");
  return {
    theme,
    toggle: () => {
      setTheme(theme === "dark" ? "light" : "dark");
    },
  };
}
