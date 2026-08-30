import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { toast } from "sonner";

import type { AppMessages, Locale } from "@/i18n";
import { isApiErrorToastShown } from "@/lib/api-client";
import type { WorkspacePreferencesPersistence } from "@/lib/workspace-preferences-persistence";
import {
  loadWorkspaceThemePreference,
  normalizeWorkspaceTheme,
} from "@/lib/workspace-theme";
import { saveUserSettingsApi } from "@/lib/workspace-api";
import { WorkspaceThemeContext } from "@/components/workspace/workspace-theme-context";
import type { AgentSettings, ThemeMode } from "@/types/resume";

export function WorkspaceThemeProvider({
  children,
  locale,
  messages,
  onLocaleChange,
  persistence,
}: {
  children: ReactNode;
  locale: Locale;
  messages: AppMessages;
  onLocaleChange: (locale: Locale) => void;
  persistence: WorkspacePreferencesPersistence;
}) {
  const [theme, setTheme] = useState<ThemeMode>(
    () => persistence.getSnapshot()?.theme ?? loadWorkspaceThemePreference(),
  );
  const [resolvedTheme, setResolvedTheme] = useState<"light" | "dark">(() =>
    document.documentElement.classList.contains("dark") ? "dark" : "light",
  );

  useEffect(() => {
    const root = document.documentElement;
    const mediaQuery = window.matchMedia?.("(prefers-color-scheme: dark)");

    function applyTheme() {
      const nextTheme =
        theme === "system"
          ? mediaQuery?.matches
            ? "dark"
            : "light"
          : theme;

      root.classList.toggle("dark", nextTheme === "dark");
      root.style.colorScheme = nextTheme;
      setResolvedTheme(nextTheme);
    }

    applyTheme();
    if (theme !== "system" || !mediaQuery) {
      return;
    }

    mediaQuery.addEventListener("change", applyTheme);
    return () => mediaQuery.removeEventListener("change", applyTheme);
  }, [theme]);

  const hydrateTheme = useCallback(
    (value: unknown) => {
      const nextTheme = normalizeWorkspaceTheme(value);
      setTheme(nextTheme);
      return nextTheme;
    },
    [],
  );

  const changeTheme = useCallback(
    (nextTheme: ThemeMode, agentSettings?: AgentSettings) => {
      setTheme(nextTheme);
      const current = persistence.getSnapshot();
      if (!current) {
        return;
      }

      const snapshot = {
        locale,
        theme: nextTheme,
        agentSettings: agentSettings ?? current.agentSettings,
      };
      persistence.enqueue(
        snapshot,
        () =>
          saveUserSettingsApi(snapshot.locale, {
            agentSettings: snapshot.agentSettings,
            theme: snapshot.theme,
          }),
        {
          onRollback(persisted) {
            onLocaleChange(persisted.locale);
            setTheme(persisted.theme);
          },
          onError(error) {
            console.error("Failed to save user settings.", error);
            if (!isApiErrorToastShown(error)) {
              toast.error(messages.loadError, { closeButton: true });
            }
          },
        },
      );
    },
    [locale, messages.loadError, onLocaleChange, persistence],
  );

  const value = useMemo(
    () => ({ changeTheme, hydrateTheme, resolvedTheme, theme }),
    [changeTheme, hydrateTheme, resolvedTheme, theme],
  );

  return (
    <WorkspaceThemeContext.Provider value={value}>
      {children}
    </WorkspaceThemeContext.Provider>
  );
}
