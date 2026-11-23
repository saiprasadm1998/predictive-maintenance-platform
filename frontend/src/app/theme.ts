/** Day (default) or Night, remembered per browser. */
export type Theme = "day" | "night";
const KEY = "pmp.theme";

export function storedTheme(): Theme {
  try {
    return localStorage.getItem(KEY) === "night" ? "night" : "day";
  } catch {
    return "day";
  }
}

export function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
  try {
    localStorage.setItem(KEY, theme);
  } catch {
    // storage blocked: the choice lasts for this page only
  }
}
