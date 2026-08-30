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
  normalizeWorkspaceTheme,
  useWorkspaceTheme,
} from "@/components/workspace/workspace-theme-context";
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
} from "@/types/resume";

type PreferencesRouteKind = "models" | "settings";

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
  const {
    changeTheme: changeWorkspaceTheme,
    hydrateTheme,
    theme,
  } = useWorkspaceTheme();
  const initialLocaleRef = useRef(locale);
  const [initialPreferences] = useState(() => persistence.getSnapshot());
  const [initialModelConfigs] = useState(() =>
    normalizeModelConfigs(preparedRouteData, locale),
  );
  const requestIdRef = useRef(0);
  const [retryKey, setRetryKey] = useState(0);
  const [hasLoaded, setHasLoaded] = useState(Boolean(preparedRouteData));
  const [hasLoadError, setHasLoadError] = useState(false);
  const [isLoading, setIsLoading] = useState(!preparedRouteData);
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
  const loadRouteData = useCallback(
    async (signal: AbortSignal) => {
      const requestId = requestIdRef.current + 1;
      requestIdRef.current = requestId;
      setIsLoading(true);
      setHasLoadError(false);
      toast.dismiss("workspace-load-error");

      try {
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

        hydrateTheme(nextTheme);
        setModelConfigs(nextModelConfigs);
        setAgentSettings(nextAgentSettings);
        persistence.hydrate(snapshot);
        setHasLoaded(true);
      } catch (error) {
        if (
          signal.aborted ||
          isAbortError(error) ||
          requestIdRef.current !== requestId
        ) {
          return;
        }

        console.error(`Failed to load the ${kind} workspace route.`, error);
        if (!isApiErrorToastShown(error)) {
          toast.error(
            getMessagesSync(initialLocaleRef.current).apiMessages.REQUEST_FAILED,
            {
              closeButton: true,
              id: "workspace-load-error",
            },
          );
        }
        setHasLoaded(false);
        setHasLoadError(true);
      } finally {
        if (
          !signal.aborted &&
          requestIdRef.current === requestId
        ) {
          setIsLoading(false);
        }
      }
    },
    [hydrateTheme, kind, persistence],
  );

  useEffect(() => {
    if (preparedRouteData && retryKey === 0) {
      const preparedModelConfigs = normalizeModelConfigs(
        preparedRouteData,
        initialLocaleRef.current,
      );
      const nextTheme = normalizeWorkspaceTheme(preparedRouteData.theme);
      hydrateTheme(nextTheme);
      persistence.hydrate({
        locale: initialLocaleRef.current,
        theme: nextTheme,
        agentSettings: normalizeAgentSettings(
          preparedRouteData.agentSettings,
          preparedModelConfigs,
        ),
      });
      return;
    }

    const controller = new AbortController();
    const loadTimer = window.setTimeout(() => {
      if (!controller.signal.aborted) {
        void loadRouteData(controller.signal);
      }
    }, 0);

    return () => {
      window.clearTimeout(loadTimer);
      controller.abort();
    };
  }, [hydrateTheme, loadRouteData, persistence, preparedRouteData, retryKey]);

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
            hydrateTheme(persisted.theme);
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
      hydrateTheme,
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
    (nextTheme: "light" | "dark" | "system") => {
      changeWorkspaceTheme(nextTheme, agentSettings);
    },
    [agentSettings, changeWorkspaceTheme],
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
    retryLoad: () => setRetryKey((current) => current + 1),
    routeData,
    theme,
  };
}
