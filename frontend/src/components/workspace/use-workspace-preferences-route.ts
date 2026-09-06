import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useWorkspaceLateralRouteData } from "@/components/workspace/use-workspace-lateral-route-data";
import { useWorkspacePreferences } from "@/components/workspace/workspace-preferences-context";
import { fetchWorkspacePageData } from "@/components/workspace/workspace-route-preparation";
import { getMessagesSync, type Locale } from "@/i18n";
import { isAbortError, isApiErrorToastShown } from "@/lib/api-client";
import { normalizeModelConfigs } from "@/lib/model-config";
import {
  dismissWorkspaceLoadError,
  showWorkspaceLoadError,
} from "@/lib/workspace-load-error";
import type { ModelConfig } from "@/types/resume";

type PreferencesRouteKind = "models" | "settings";

export function useWorkspacePreferencesRoute({
  kind,
  locale,
}: {
  kind: PreferencesRouteKind;
  locale: Locale;
}) {
  const preparedRouteData = useWorkspaceLateralRouteData(kind);
  const {
    agentSettings,
    changeAgentSettings,
    changeLocale,
    changeTheme,
    persistence,
    reconcileModels,
    theme,
  } = useWorkspacePreferences();
  const initialLocaleRef = useRef(locale);
  const requestIdRef = useRef(0);
  const [retryKey, setRetryKey] = useState(0);
  const [hasPreparedData] = useState(
    () => Boolean(preparedRouteData) && agentSettings !== null,
  );
  const [hasLoaded, setHasLoaded] = useState(hasPreparedData);
  const [hasLoadError, setHasLoadError] = useState(false);
  const [isLoading, setIsLoading] = useState(!hasPreparedData);
  const [modelConfigs, setModelConfigs] = useState<ModelConfig[]>(() =>
    normalizeModelConfigs(preparedRouteData, locale),
  );
  const routeData = useMemo(
    () => agentSettings ? { agentSettings, modelConfigs, theme } : null,
    [agentSettings, modelConfigs, theme],
  );
  const loadRouteData = useCallback(
    async (signal: AbortSignal) => {
      const requestId = requestIdRef.current + 1;
      requestIdRef.current = requestId;
      setIsLoading(true);
      setHasLoadError(false);
      dismissWorkspaceLoadError();

      try {
        const source = await fetchWorkspacePageData(kind, persistence, {
          notifyOnError: false,
          signal,
        });
        if (signal.aborted || requestIdRef.current !== requestId) {
          return;
        }

        setModelConfigs(normalizeModelConfigs(source.data, initialLocaleRef.current));
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
          showWorkspaceLoadError(
            getMessagesSync(initialLocaleRef.current).apiMessages.REQUEST_FAILED,
          );
        }
        setHasLoaded(false);
        setHasLoadError(true);
      } finally {
        if (!signal.aborted && requestIdRef.current === requestId) {
          setIsLoading(false);
        }
      }
    },
    [kind, persistence],
  );
  const needsPreferences = agentSettings === null;

  useEffect(() => {
    if (hasPreparedData && retryKey === 0) {
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
  }, [hasPreparedData, loadRouteData, retryKey]);

  const changeModelConfigs = useCallback(
    (nextModelConfigs: ModelConfig[]) => {
      reconcileModels(nextModelConfigs);
      setModelConfigs(nextModelConfigs);
    },
    [reconcileModels],
  );

  return {
    agentSettings,
    changeAgentSettings,
    changeLocale,
    changeModelConfigs,
    changeTheme,
    hasLoaded: hasLoaded && !needsPreferences,
    hasLoadError,
    isLoading: isLoading || needsPreferences,
    modelConfigs,
    retryLoad: () => setRetryKey((current) => current + 1),
    routeData,
    theme,
  };
}
