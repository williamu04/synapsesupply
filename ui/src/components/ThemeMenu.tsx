import { useEffect, useRef } from "react";
import settingsDark from "../assets/settings-dark.svg";
import settingsLight from "../assets/settings-light.svg";
import type { Contrast, ThemeMode, ThemePref } from "../theme";

const MODES: [ThemeMode, string][] = [["light", "Light"], ["dark", "Dark"], ["system", "System"]];
const CONTRASTS: [Contrast, string][] = [["standard", "Standard"], ["medium", "Medium"], ["high", "High"]];

/** The profile's settings gear: theme and contrast, from the style guide's six schemes. Closes on an
 *  outside click or Escape. */
export function ThemeMenu({ pref, onChange }: { pref: ThemePref; onChange: (pref: ThemePref) => void }) {
  const menu = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    const close = (e: Event) => {
      const el = menu.current;
      if (!el?.open) return;
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !el.contains(e.target as Node)) {
        el.open = false;
        if (e instanceof KeyboardEvent) el.querySelector("summary")?.focus();
      }
    };
    document.addEventListener("pointerdown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("pointerdown", close);
      document.removeEventListener("keydown", close);
    };
  }, []);

  return (
    <details className="theme-menu" ref={menu}>
      <summary aria-label="Display settings" title="Display settings">
        <img className="only-light" src={settingsLight} width={15} height={16} alt="" />
        <img className="only-dark" src={settingsDark} width={15} height={16} alt="" />
      </summary>
      <div className="menu">
        <fieldset>
          <legend>Theme</legend>
          {MODES.map(([mode, label]) => (
            <label key={mode}>
              <input type="radio" name="theme-mode" checked={pref.mode === mode}
                     onChange={() => onChange({ ...pref, mode })} /> {label}
            </label>
          ))}
        </fieldset>
        <fieldset>
          <legend>Contrast</legend>
          {CONTRASTS.map(([contrast, label]) => (
            <label key={contrast}>
              <input type="radio" name="theme-contrast" checked={pref.contrast === contrast}
                     onChange={() => onChange({ ...pref, contrast })} /> {label}
            </label>
          ))}
        </fieldset>
      </div>
    </details>
  );
}
