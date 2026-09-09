import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Outlet, useLocation } from "react-router-dom";

import { WorkspacePreferencesContext } from "@/components/workspace/workspace-preferences-context";
import { getMessagesSync, type AppMessages, type Locale } from "@/i18n";
import { normalizeAgentSettings } from "@/lib/agent-settings";
import { notifyApiError } from "@/lib/api-error-notifier";
import { saveUserSettingsApi } from "@/lib/workspace-api";
import {
  createWorkspacePreferencesPersistence,
  type WorkspacePreferencesSnapshot,
} from "@/lib/workspace-preferences-persistence";
import { getWorkspaceLateralRouteHandoff } from "@/lib/workspace-route-memory";
import {
  applyWorkspaceTheme,
  loadWorkspaceThemePreference,
  saveWorkspaceThemePreference,
} from "@/lib/workspace-theme";
import type { AgentSettings, ThemeMode } from "@/types/resume";

export function WorkspacePreferencesProvider({
  locale,
  messages,
  onLocaleChange,
}: {
  locale: Locale;
  messages: AppMessages;
  onLocaleChange: (locale: Locale) => Promise<boolean>;
}) {
  const location = useLocation();
  const [initial] = useState<WorkspacePreferencesSnapshot>(() => {
    const prepared = getWorkspaceLateralRouteHandoff(location.state);
    return {
      locale,
      theme: prepared?.data.theme ?? loadWorkspaceThemePreference(),
      agentSettings:
        prepared && "agentSettings" in prepared.data
          ? normalizeAgentSettings(
              prepared.data.agentSettings,
              prepared.data.modelConfigs,
            )
          : null,
    };
  });
  const [snapshot, setSnapshot] = useState(initial);
  const activeRef = useRef(true);
  const localeRequestRef = useRef(0);
  const pendingLocaleRef = useRef(false);
  const [persistence] = useState(() =>
    createWorkspacePreferencesPersistence(initial, {
      onChange: setSnapshot,
      onError(error, errorLocale) {
        console.error("Failed to save user settings.", error);
        notifyApiError(error, getMessagesSync(errorLocale).loadError);
      },
      save(patch, saveLocale) {
        const { theme, agentSettings } = patch;
        return saveUserSettingsApi(saveLocale, {
          ...(theme !== undefined ? { theme } : {}),
          ...(agentSettings !== undefined ? { agentSettings } : {}),
        });
      },
    }),
  );
  useLayoutEffect(() => {
    if (!pendingLocaleRef.current) {
      persistence.synchronizeLocale(locale);
    }
  }, [locale, persistence]);
  const [resolvedTheme, setResolvedTheme] = useState<"light" | "dark">(() =>
    document.documentElement.classList.contains("dark") ? "dark" : "light",
  );

  useLayoutEffect(() => {
    saveWorkspaceThemePreference(initial.theme);
  }, [initial]);

  useEffect(() => {
    activeRef.current = true;
    return () => {
      activeRef.current = false;
      localeRequestRef.current += 1;
      pendingLocaleRef.current = false;
      persistence.reset(initial);
    };
  }, [initial, persistence]);

  useLayoutEffect(() => {
    const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");
    const apply = () => {
      const next =
        snapshot.theme === "system"
          ? mediaQuery.matches
            ? "dark"
            : "light"
          : snapshot.theme;
      applyWorkspaceTheme(next);
      setResolvedTheme(next);
    };
    apply();
    if (snapshot.theme !== "system") {
      return;
    }
    mediaQuery.addEventListener("change", apply);
    return () => mediaQuery.removeEventListener("change", apply);
  }, [snapshot.theme]);

  const changeTheme = useCallback(
    (theme: ThemeMode) => persistence.change({ theme }),
    [persistence],
  );
  const changeAgentSettings = useCallback(
    (agentSettings: AgentSettings) => persistence.change({ agentSettings }),
    [persistence],
  );
  const changeLocale = useCallback(
    (nextLocale: Locale) => {
      const requestId = ++localeRequestRef.current;
      pendingLocaleRef.current = true;
      void onLocaleChange(nextLocale).then(async (accepted) => {
        if (requestId !== localeRequestRef.current || !activeRef.current) {
          return;
        }
        if (accepted) {
          persistence.change({ locale: nextLocale });
        }
        await persistence.flush();
        if (requestId !== localeRequestRef.current || !activeRef.current) {
          return;
        }
        await onLocaleChange(persistence.getSnapshot().locale);
        if (requestId === localeRequestRef.current && activeRef.current) {
          pendingLocaleRef.current = false;
        }
      });
    },
    [onLocaleChange, persistence],
  );
  const value = useMemo(
    () => ({
      agentSettings: snapshot.agentSettings,
      changeAgentSettings,
      changeLocale,
      changeTheme,
      locale,
      messages,
      persistence,
      reconcileModels: persistence.reconcileModels,
      resolvedTheme,
      theme: snapshot.theme,
    }),
    [
      changeAgentSettings,
      changeLocale,
      changeTheme,
      locale,
      messages,
      persistence,
      resolvedTheme,
      snapshot,
    ],
  );

  return (
    <WorkspacePreferencesContext.Provider value={value}>
      <Outlet />
    </WorkspacePreferencesContext.Provider>
  );
}
