import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import {
  createDefaultAgentSettings,
  normalizeAgentSettings,
} from "@/lib/agent-settings";
import { isAbortError, isApiErrorToastShown } from "@/lib/api-client";
import { normalizeModelConfigs } from "@/lib/model-config";
import {
  type WorkspacePreferencesPersistence,
  type WorkspacePreferencesSnapshot,
} from "@/lib/workspace-preferences-persistence";
import {
  fetchWorkspaceRouteData,
  saveUserSettingsApi,
} from "@/lib/workspace-api";
import { getMessagesSync, type AppMessages, type Locale } from "@/i18n";
import type {
  AgentSettings,
  ModelConfig,
  ThemeMode,
} from "@/types/resume";

type PreferencesRouteKind = "models" | "settings";

function normalizeWorkspaceTheme(value: unknown): ThemeMode {
  return value === "dark" || value === "system" ? value : "light";
}

export function useWorkspacePreferencesRoute({
  kind,
  locale,
  messages,
  onLocaleChange,
  persistence,
}: {
  kind: PreferencesRouteKind;
  locale: Locale;
  messages: AppMessages;
  onLocaleChange: (locale: Locale) => void;
  persistence: WorkspacePreferencesPersistence;
}) {
  const initialLocaleRef = useRef(locale);
  const [initialPreferences] = useState(() => persistence.getSnapshot());
  const requestIdRef = useRef(0);
  const [retryKey, setRetryKey] = useState(0);
  const [hasLoaded, setHasLoaded] = useState(false);
  const [hasLoadError, setHasLoadError] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [theme, setTheme] = useState<ThemeMode>(
    () => initialPreferences?.theme ?? "light",
  );
  const [resolvedTheme, setResolvedTheme] = useState<"light" | "dark">(
    "light",
  );
  const [modelConfigs, setModelConfigs] = useState<ModelConfig[]>([]);
  const [agentSettings, setAgentSettings] = useState<AgentSettings>(
    () => initialPreferences?.agentSettings ?? createDefaultAgentSettings(),
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

  const loadRouteData = useCallback(
    async (signal: AbortSignal) => {
      const requestId = requestIdRef.current + 1;
      requestIdRef.current = requestId;
      setIsLoading(true);
      setHasLoadError(false);
      toast.dismiss("workspace-load-error");

      try {
        // A previous route may still be committing a full settings snapshot.
        // Waiting here prevents this route from hydrating stale server state.
        await persistence.flush();
        if (signal.aborted || requestIdRef.current !== requestId) {
          return;
        }

        const source = await fetchWorkspaceRouteData(kind, {
          notifyOnError: false,
          signal,
        });
        if (signal.aborted || requestIdRef.current !== requestId) {
          return;
        }

        const nextModelConfigs = normalizeModelConfigs(
          source.data,
          initialLocaleRef.current,
        );
        const nextAgentSettings = normalizeAgentSettings(
          source.data.agentSettings,
          nextModelConfigs,
        );
        const nextTheme = normalizeWorkspaceTheme(source.data.theme);
        const snapshot: WorkspacePreferencesSnapshot = {
          locale: initialLocaleRef.current,
          theme: nextTheme,
          agentSettings: nextAgentSettings,
        };

        setTheme(nextTheme);
        setModelConfigs(nextModelConfigs);
        setAgentSettings(nextAgentSettings);
        persistence.hydrate(snapshot);
        setHasLoaded(true);
      } catch (error) {
        if (isAbortError(error)) {
          return;
        }
        if (requestIdRef.current !== requestId) {
          return;
        }

        console.error(`Failed to load the ${kind} workspace route.`, error);
        if (!isApiErrorToastShown(error)) {
          toast.error(
            getMessagesSync(initialLocaleRef.current).apiMessages
              .REQUEST_FAILED,
            {
              closeButton: true,
              id: "workspace-load-error",
            },
          );
        }
        setHasLoaded(false);
        setHasLoadError(true);
      } finally {
        if (requestIdRef.current === requestId) {
          setIsLoading(false);
        }
      }
    },
    [kind, persistence],
  );

  useEffect(() => {
    const controller = new AbortController();
    // Defer transport so StrictMode's development preflight can abort before
    // a duplicate route request leaves the browser.
    const loadTimer = window.setTimeout(() => {
      if (!controller.signal.aborted) {
        void loadRouteData(controller.signal);
      }
    }, 0);

    return () => {
      window.clearTimeout(loadTimer);
      controller.abort();
    };
  }, [loadRouteData, retryKey]);

  const persistSnapshot = useCallback(
    (
      snapshot: WorkspacePreferencesSnapshot,
      rollbackModelConfigs: ModelConfig[] = modelConfigs,
    ) => {
      if (!hasLoaded || isLoading) {
        return;
      }

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
            setAgentSettings(
              normalizeAgentSettings(
                persisted.agentSettings,
                rollbackModelConfigs,
              ),
            );
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
    [
      hasLoaded,
      isLoading,
      messages.loadError,
      modelConfigs,
      onLocaleChange,
      persistence,
    ],
  );

  const changeLocale = useCallback(
    (nextLocale: Locale) => {
      onLocaleChange(nextLocale);
      persistSnapshot({
        locale: nextLocale,
        theme,
        agentSettings,
      });
    },
    [agentSettings, onLocaleChange, persistSnapshot, theme],
  );

  const changeTheme = useCallback(
    (nextTheme: ThemeMode) => {
      setTheme(nextTheme);
      persistSnapshot({
        locale,
        theme: nextTheme,
        agentSettings,
      });
    },
    [agentSettings, locale, persistSnapshot],
  );

  const changeAgentSettings = useCallback(
    (nextSettings: AgentSettings) => {
      const normalizedSettings = normalizeAgentSettings(
        nextSettings,
        modelConfigs,
      );
      setAgentSettings(normalizedSettings);
      persistSnapshot({
        locale,
        theme,
        agentSettings: normalizedSettings,
      });
    },
    [locale, modelConfigs, persistSnapshot, theme],
  );

  const changeModelConfigs = useCallback(
    (nextModelConfigs: ModelConfig[]) => {
      const normalizedSettings = normalizeAgentSettings(
        agentSettings,
        nextModelConfigs,
      );

      setModelConfigs(nextModelConfigs);
      if (
        normalizedSettings.defaultModelId !== agentSettings.defaultModelId
      ) {
        setAgentSettings(normalizedSettings);
        persistSnapshot(
          {
            locale,
            theme,
            agentSettings: normalizedSettings,
          },
          nextModelConfigs,
        );
      }
    },
    [agentSettings, locale, persistSnapshot, theme],
  );

  return {
    agentSettings,
    changeAgentSettings,
    changeLocale,
    changeModelConfigs,
    changeTheme,
    hasLoaded,
    hasLoadError,
    isLoading,
    modelConfigs,
    resolvedTheme,
    retryLoad: () => setRetryKey((current) => current + 1),
    theme,
  };
}
