import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import type { AppMessages, Locale } from "@/i18n";
import {
  createDefaultAgentSettings,
  normalizeAgentSettings,
} from "@/lib/agent-settings";
import { isApiErrorToastShown } from "@/lib/api-client";
import { normalizeModelConfigs } from "@/lib/model-config";
import type { WorkspacePreferencesPersistence } from "@/lib/workspace-preferences-persistence";
import { saveUserSettingsApi } from "@/lib/workspace-api";
import type { ResumeEditorRouteData } from "@/lib/workspace-route-data";
import type {
  AgentSettings,
  ModelConfig,
  ThemeMode,
} from "@/types/resume";

function normalizeTheme(value: unknown): ThemeMode {
  return value === "dark" || value === "system" ? value : "light";
}

interface ResumeDetailPreferencesOptions {
  initialTheme?: ThemeMode;
  isLoading: () => boolean;
  locale: Locale;
  messages: AppMessages;
  onLocaleChange: (locale: Locale) => void;
  persistence: WorkspacePreferencesPersistence;
}

/** Owns route-local preference UI and the shared serialized write boundary. */
export function useResumeDetailPreferences({
  initialTheme,
  isLoading,
  locale,
  messages,
  onLocaleChange,
  persistence,
}: ResumeDetailPreferencesOptions) {
  const initialLocaleRef = useRef(locale);
  const initialSnapshot = persistence.getSnapshot();
  const [theme, setTheme] = useState<ThemeMode>(() =>
    initialTheme ? normalizeTheme(initialTheme) : initialSnapshot?.theme ?? "light",
  );
  const [resolvedTheme, setResolvedTheme] = useState<"light" | "dark">(() =>
    document.documentElement.classList.contains("dark") ? "dark" : "light",
  );
  const [modelConfigs, setModelConfigs] = useState<ModelConfig[]>([]);
  const [agentSettings, setAgentSettings] = useState<AgentSettings>(
    initialSnapshot?.agentSettings ?? createDefaultAgentSettings(),
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

  const hydrateRoutePreferences = useCallback(
    (source: ResumeEditorRouteData) => {
      const nextModels = normalizeModelConfigs(source, initialLocaleRef.current);
      const nextAgentSettings = normalizeAgentSettings(
        source.agentSettings,
        nextModels,
      );
      const nextTheme = source.theme
        ? normalizeTheme(source.theme)
        : theme;

      setTheme(nextTheme);
      setModelConfigs(nextModels);
      setAgentSettings(nextAgentSettings);
      persistence.hydrate({
        agentSettings: nextAgentSettings,
        locale: initialLocaleRef.current,
        theme: nextTheme,
      });
    },
    [persistence, theme],
  );

  const persist = useCallback(
    (nextTheme: ThemeMode, nextAgentSettings: AgentSettings) => {
      if (isLoading()) {
        return;
      }
      const snapshot = {
        agentSettings: nextAgentSettings,
        locale,
        theme: nextTheme,
      };
      persistence.enqueue(
        snapshot,
        () =>
          saveUserSettingsApi(snapshot.locale, {
            agentSettings: snapshot.agentSettings,
            theme: snapshot.theme,
          }),
        {
          onError(error) {
            console.error("Failed to save user settings.", error);
            if (!isApiErrorToastShown(error)) {
              toast.error(messages.loadError, { closeButton: true });
            }
          },
          onRollback(persisted) {
            onLocaleChange(persisted.locale);
            setTheme(persisted.theme);
            setAgentSettings(
              normalizeAgentSettings(persisted.agentSettings, modelConfigs),
            );
          },
        },
      );
    },
    [
      isLoading,
      locale,
      messages.loadError,
      modelConfigs,
      onLocaleChange,
      persistence,
    ],
  );

  const changeTheme = useCallback(
    (nextTheme: ThemeMode) => {
      setTheme(nextTheme);
      persist(nextTheme, agentSettings);
    },
    [agentSettings, persist],
  );
  const changeAgentSettings = useCallback(
    (nextSettings: AgentSettings) => {
      const normalized = normalizeAgentSettings(nextSettings, modelConfigs);
      setAgentSettings(normalized);
      persist(theme, normalized);
    },
    [modelConfigs, persist, theme],
  );

  return {
    agentSettings,
    changeAgentSettings,
    changeTheme,
    hydrateRoutePreferences,
    modelConfigs,
    resolvedTheme,
    theme,
  };
}
