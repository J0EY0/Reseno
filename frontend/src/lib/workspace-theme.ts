import type { ThemeMode } from "@/types/resume";

export const workspaceThemePreferenceKey = "resumate-theme";

export function applyWorkspaceTheme(theme: "light" | "dark") {
  const transitionBlocker = document.createElement("style");
  transitionBlocker.textContent =
    "*,*::before,*::after{transition:none!important}";
  document.head.appendChild(transitionBlocker);

  const root = document.documentElement;
  root.classList.toggle("dark", theme === "dark");
  root.style.colorScheme = theme;

  window.getComputedStyle(document.body);
  window.setTimeout(() => transitionBlocker.remove(), 1);
}

function normalizeWorkspaceTheme(value: unknown): ThemeMode {
  return value === "dark" || value === "system" ? value : "light";
}

export function loadWorkspaceThemePreference(): ThemeMode {
  if (typeof window === "undefined") {
    return "light";
  }

  try {
    return normalizeWorkspaceTheme(
      window.localStorage.getItem(workspaceThemePreferenceKey),
    );
  } catch {
    return "light";
  }
}

export function saveWorkspaceThemePreference(theme: ThemeMode) {
  if (typeof window === "undefined") {
    return;
  }

  try {
    window.localStorage.setItem(workspaceThemePreferenceKey, theme);
  } catch {
    // The server remains authoritative when local storage is unavailable.
  }
}
