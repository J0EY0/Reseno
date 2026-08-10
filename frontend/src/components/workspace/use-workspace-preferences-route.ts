import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import {
  createDefaultAgentSettings,
  normalizeAgentSettings,
} from "@/lib/agent-settings";
import { isAbortError, isApiErrorToastShown } from "@/lib/api-client";
import { normalizeModelConfigs } from "@/lib/model-config";
import { useWorkspaceLateralRouteData } from "@/components/workspace/use-workspace-lateral-route-data";
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
  const preparedRouteData = useWorkspaceLateralRouteData(kind);
  const initialLocaleRef = useRef(locale);
  const [initialPreferences] = useState(() => persistence.getSnapshot());
  const [initialModelConfigs] = useState(() =>
    normalizeModelConfigs(preparedRouteData, locale),
  );
  const requestIdRef = useRef(0);
  const routeMutationEpochRef = useRef(0);
  const [retryKey, setRetryKey] = useState(0);
  const [hasLoaded, setHasLoaded] = useState(Boolean(preparedRouteData));
  const [hasLoadError, setHasLoadError] = useState(false);
  const [isLoading, setIsLoading] = useState(!preparedRouteData);
  const [theme, setTheme] = useState<ThemeMode>(
    () =>
      preparedRouteData
        ? normalizeWorkspaceTheme(preparedRouteData.theme)
        : initialPreferences?.theme ?? "light",
  );
  const [resolvedTheme, setResolvedTheme] = useState<"light" | "dark">(
    "light",
  );
  const [modelConfigs, setModelConfigs] =
    useState<ModelConfig[]>(initialModelConfigs);
  const [agentSettings, setAgentSettings] = useState<AgentSettings>(
    () =>
      preparedRouteData
        ? normalizeAgentSettings(
            preparedRouteData.agentSettings,
            initialModelConfigs,
          )
        : initialPreferences?.agentSettings ?? createDefaultAgentSettings(),
  );
  const routeData = useMemo(
    () => ({ agentSettings, modelConfigs, theme }),
    [agentSettings, modelConfigs, theme],
  );
  const markRouteMutation = useCallback(() => {
    routeMutationEpochRef.current += 1;
  }, []);

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
    async (signal: AbortSignal, isPreparedCalibration: boolean) => {
      const requestId = requestIdRef.current + 1;
      requestIdRef.current = requestId;
      if (!isPreparedCalibration) {
        setIsLoading(true);
        setHasLoadError(false);
        toast.dismiss("workspace-load-error");
      }

      try {
        while (!signal.aborted && requestIdRef.current === requestId) {
          const mutationEpoch = routeMutationEpochRef.current;
          try {
            // A previous route may still be committing a full settings snapshot.
            await persistence.flush();
            if (signal.aborted || requestIdRef.current !== requestId) {
              return;
            }
            if (
              isPreparedCalibration &&
              routeMutationEpochRef.current !== mutationEpoch
            ) {
              continue;
            }

            const source = await fetchWorkspaceRouteData(
              kind,
              isPreparedCalibration
                ? { notifyOnError: false }
                : { notifyOnError: false, signal },
            );
            if (signal.aborted || requestIdRef.current !== requestId) {
              return;
            }
            if (
              isPreparedCalibration &&
              routeMutationEpochRef.current !== mutationEpoch
            ) {
              continue;
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
            return;
          } catch (error) {
            if (signal.aborted || isAbortError(error)) {
              return;
            }
            if (requestIdRef.current !== requestId) {
              return;
            }
            if (
              isPreparedCalibration &&
              routeMutationEpochRef.current !== mutationEpoch
            ) {
              continue;
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
            if (!isPreparedCalibration) {
              setHasLoaded(false);
              setHasLoadError(true);
            }
            return;
          }
        }
      } finally {
        if (
          !isPreparedCalibration &&
          !signal.aborted &&
          requestIdRef.current === requestId
        ) {
          setIsLoading(false);
        }
      }
    },
    [kind, persistence],
  );

  useEffect(() => {
    const isPreparedCalibration = Boolean(preparedRouteData) && retryKey === 0;
    if (isPreparedCalibration && preparedRouteData) {
      const preparedModelConfigs = normalizeModelConfigs(
        preparedRouteData,
        initialLocaleRef.current,
      );
      persistence.hydrate({
        locale: initialLocaleRef.current,
        theme: normalizeWorkspaceTheme(preparedRouteData.theme),
        agentSettings: normalizeAgentSettings(
          preparedRouteData.agentSettings,
          preparedModelConfigs,
        ),
      });
    }

    const controller = new AbortController();
    // Defer transport so StrictMode's development preflight can abort before
    // a duplicate route request leaves the browser.
    const loadTimer = window.setTimeout(() => {
      if (!controller.signal.aborted) {
        void loadRouteData(controller.signal, isPreparedCalibration);
      }
    }, 0);

    return () => {
      window.clearTimeout(loadTimer);
      controller.abort();
    };
  }, [loadRouteData, persistence, preparedRouteData, retryKey]);

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
      markRouteMutation();
      onLocaleChange(nextLocale);
      persistSnapshot({
        locale: nextLocale,
        theme,
        agentSettings,
      });
    },
    [agentSettings, markRouteMutation, onLocaleChange, persistSnapshot, theme],
  );

  const changeTheme = useCallback(
    (nextTheme: ThemeMode) => {
      markRouteMutation();
      setTheme(nextTheme);
      persistSnapshot({
        locale,
        theme: nextTheme,
        agentSettings,
      });
    },
    [agentSettings, locale, markRouteMutation, persistSnapshot],
  );

  const changeAgentSettings = useCallback(
    (nextSettings: AgentSettings) => {
      markRouteMutation();
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
    [locale, markRouteMutation, modelConfigs, persistSnapshot, theme],
  );

  const changeModelConfigs = useCallback(
    (nextModelConfigs: ModelConfig[]) => {
      markRouteMutation();
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
    [agentSettings, locale, markRouteMutation, persistSnapshot, theme],
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
    routeData,
    theme,
  };
}
