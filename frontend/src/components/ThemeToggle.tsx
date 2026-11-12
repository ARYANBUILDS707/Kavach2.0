import { useTheme } from "../lib/theme";

/** Round outlined toggle between the light and dark themes (reference header control). */
export function ThemeToggle() {
  const { theme, toggle } = useTheme();
  const next = theme === "dark" ? "light" : "dark";
  return (
    <button type="button" className="theme-toggle" onClick={toggle} aria-label={`Switch to ${next} theme`}>
      <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
        {theme === "dark" ? (
          <path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5Z" />
        ) : (
          <>
            <circle cx="12" cy="12" r="4" />
            <path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4" />
          </>
        )}
      </svg>
    </button>
  );
}
