// Theme preference: light / dark / system, each in standard, medium or high contrast. Applied as one
// of the style guide's classes on <html> (src/theme/*.css, Material 3 teal scheme).

export type ThemeMode = "system" | "light" | "dark";
export type Contrast = "standard" | "medium" | "high";
export interface ThemePref { mode: ThemeMode; contrast: Contrast }

const KEY = "theme";
const SUFFIX: Record<Contrast, string> = { standard: "", medium: "-medium-contrast", high: "-high-contrast" };
const CLASSES = ["light", "dark"].flatMap((base) => Object.values(SUFFIX).map((s) => base + s));
// The design's screens are light; the projector-friendly default.
export const DEFAULT_THEME: ThemePref = { mode: "light", contrast: "standard" };

/** The style-guide class for a preference, e.g. {dark, high} -> "dark-high-contrast". */
export function themeClass(pref: ThemePref, systemDark: boolean): string {
  const base = pref.mode === "system" ? (systemDark ? "dark" : "light") : pref.mode;
  return base + SUFFIX[pref.contrast];
}

export function loadTheme(): ThemePref {
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) ?? "null") as Partial<ThemePref> | null;
    if (saved && saved.mode && saved.contrast && saved.contrast in SUFFIX) return saved as ThemePref;
  } catch { /* storage unavailable or corrupt: use the default */ }
  return DEFAULT_THEME;
}

export function saveTheme(pref: ThemePref): void {
  try { localStorage.setItem(KEY, JSON.stringify(pref)); } catch { /* storage unavailable */ }
}

const systemQuery = () => window.matchMedia("(prefers-color-scheme: dark)");

export function applyTheme(pref: ThemePref): void {
  const root = document.documentElement;
  root.classList.remove(...CLASSES);
  root.classList.add(themeClass(pref, systemQuery().matches));
}

/** Re-apply when the OS switches light/dark while the preference is "system". Returns an unsubscribe. */
export function followSystem(pref: ThemePref): () => void {
  const query = systemQuery();
  const onChange = () => applyTheme(pref);
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}
