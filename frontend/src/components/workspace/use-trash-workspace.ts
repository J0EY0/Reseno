import {
  startTransition,
  useCallback,
  useDeferredValue,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { toast } from "sonner";

import { getMessagesSync, type AppMessages, type Locale } from "@/i18n";
import { createDefaultAgentSettings } from "@/lib/agent-settings";
import { isAbortError, isApiErrorToastShown } from "@/lib/api-client";
import { createTemplatePreviewResume } from "@/lib/template-preview-resume";
import { getTemplateCatalog } from "@/lib/templates";
import { useWorkspaceLateralRouteData } from "@/components/workspace/use-workspace-lateral-route-data";
import type { WorkspacePreferencesPersistence } from "@/lib/workspace-preferences-persistence";
import {
  deleteResumeForeverApi,
  deleteTemplateForeverApi,
  fetchWorkspaceRouteData,
  restoreResumeApi,
  restoreTemplateApi,
  saveUserSettingsApi,
} from "@/lib/workspace-api";
import type {
  DeletedResumeTemplateDefinition,
  DeletedResumeWorkspaceItem,
  ResumeTemplateDefinition,
  ThemeMode,
} from "@/types/resume";

function normalizeWorkspaceTheme(value: unknown): ThemeMode {
  return value === "dark" || value === "system" ? value : "light";
}

export function useTrashWorkspace({
  locale,
  messages,
  onLocaleChange,
  persistence,
}: {
  locale: Locale;
  messages: AppMessages;
  onLocaleChange: (locale: Locale) => void;
  persistence: WorkspacePreferencesPersistence;
}) {
  const preparedRouteData = useWorkspaceLateralRouteData("trash");
  const initialLocaleRef = useRef(locale);
  const requestIdRef = useRef(0);
  const routeMutationEpochRef = useRef(0);
  const [retryKey, setRetryKey] = useState(0);
  const [hasLoaded, setHasLoaded] = useState(Boolean(preparedRouteData));
  const [hasLoadError, setHasLoadError] = useState(false);
  const [isLoading, setIsLoading] = useState(!preparedRouteData);
  const [theme, setTheme] = useState<ThemeMode>(
    () =>
      preparedRouteData?.theme
        ? normalizeWorkspaceTheme(preparedRouteData.theme)
        : persistence.getSnapshot()?.theme ?? "light",
  );
  const [resolvedTheme, setResolvedTheme] = useState<"light" | "dark">(() =>
    document.documentElement.classList.contains("dark") ? "dark" : "light",
  );
  const [customTemplates, setCustomTemplates] = useState<
    ResumeTemplateDefinition[]
  >(() => preparedRouteData?.customTemplates ?? []);
  const [defaultTemplateId, setDefaultTemplateId] = useState(
    () => preparedRouteData?.defaultTemplateId ?? "minimal",
  );
  const [deletedResumes, setDeletedResumes] = useState<
    DeletedResumeWorkspaceItem[]
  >(() => preparedRouteData?.deletedResumes ?? []);
  const [deletedTemplates, setDeletedTemplates] = useState<
    DeletedResumeTemplateDefinition[]
  >(() => preparedRouteData?.deletedTemplates ?? []);
  const templates = useMemo(
    () => getTemplateCatalog(messages, customTemplates),
    [customTemplates, messages],
  );
  const routeData = useMemo(
    () => ({
      customTemplates,
      defaultTemplateId,
      deletedResumes,
      deletedTemplates,
      theme,
    }),
    [customTemplates, defaultTemplateId, deletedResumes, deletedTemplates, theme],
  );
  const templatePreviewResume = useDeferredValue(
    useMemo(() => createTemplatePreviewResume(messages), [messages]),
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
              "trash",
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

            const persistedPreferences = persistence.getSnapshot();
            const nextTheme = source.data.theme
              ? normalizeWorkspaceTheme(source.data.theme)
              : persistedPreferences?.theme ?? "light";
            const persistedAgentSettings =
              persistedPreferences?.agentSettings ??
              createDefaultAgentSettings();

            setTheme(nextTheme);
            setCustomTemplates(source.data.customTemplates);
            setDefaultTemplateId(source.data.defaultTemplateId);
            setDeletedResumes(source.data.deletedResumes);
            setDeletedTemplates(source.data.deletedTemplates);
            persistence.hydrate({
              locale: initialLocaleRef.current,
              theme: nextTheme,
              agentSettings: persistedAgentSettings,
            });
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

            console.error("Failed to load the trash workspace route.", error);
            if (!isApiErrorToastShown(error)) {
              toast.error(
                getMessagesSync(initialLocaleRef.current).apiMessages
                  .REQUEST_FAILED,
                { closeButton: true, id: "workspace-load-error" },
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
    [persistence],
  );

  useEffect(() => {
    const isPreparedCalibration = Boolean(preparedRouteData) && retryKey === 0;
    if (isPreparedCalibration && preparedRouteData) {
      const persistedPreferences = persistence.getSnapshot();
      persistence.hydrate({
        locale: initialLocaleRef.current,
        theme: preparedRouteData.theme
          ? normalizeWorkspaceTheme(preparedRouteData.theme)
          : persistedPreferences?.theme ?? "light",
        agentSettings:
          persistedPreferences?.agentSettings ?? createDefaultAgentSettings(),
      });
    }

    const controller = new AbortController();
    // Suppress StrictMode's development preflight before transport begins,
    // then abort a real request when route ownership changes.
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

  const changeTheme = useCallback(
    (nextTheme: ThemeMode) => {
      markRouteMutation();
      setTheme(nextTheme);
      if (!hasLoaded || isLoading) {
        return;
      }

      const snapshot = {
        locale,
        theme: nextTheme,
        agentSettings:
          persistence.getSnapshot()?.agentSettings ??
          createDefaultAgentSettings(),
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
    [hasLoaded, isLoading, locale, markRouteMutation, messages.loadError, onLocaleChange, persistence],
  );

  const restoreResumes = useCallback(
    async (resumeIds: string[]) => {
      if (
        resumeIds.length === 0 ||
        !deletedResumes.some((item) => resumeIds.includes(item.id))
      ) {
        return false;
      }

      try {
        for (const resumeId of resumeIds) {
          await restoreResumeApi(resumeId);
        }
      } catch (error) {
        console.error("Failed to restore resume.", error);
        if (!isApiErrorToastShown(error)) {
          toast.error(messages.loadError, { closeButton: true });
        }
        return false;
      }

      markRouteMutation();
      startTransition(() => {
        setDeletedResumes((current) =>
          current.filter((item) => !resumeIds.includes(item.id)),
        );
      });
      toast.success(
        resumeIds.length > 1 ? messages.resumesRestored : messages.resumeRestored,
        { closeButton: true },
      );
      return true;
    },
    [deletedResumes, markRouteMutation, messages],
  );

  const permanentlyDeleteResumes = useCallback(
    async (resumeIds: string[]) => {
      if (resumeIds.length === 0) {
        return false;
      }

      try {
        for (const resumeId of resumeIds) {
          await deleteResumeForeverApi(resumeId);
        }
      } catch (error) {
        console.error("Failed to permanently delete resume.", error);
        if (!isApiErrorToastShown(error)) {
          toast.error(messages.loadError, { closeButton: true });
        }
        return false;
      }

      markRouteMutation();
      startTransition(() => {
        setDeletedResumes((current) =>
          current.filter((item) => !resumeIds.includes(item.id)),
        );
      });
      toast.success(
        resumeIds.length > 1
          ? messages.resumesDeletedForever
          : messages.resumeDeletedForever,
        { closeButton: true },
      );
      return true;
    },
    [markRouteMutation, messages],
  );

  const restoreTemplates = useCallback(
    async (templateIds: string[]) => {
      const restoring = deletedTemplates.filter((item) =>
        templateIds.includes(item.id),
      );
      if (templateIds.length === 0 || restoring.length === 0) {
        return false;
      }

      let restoredItems: ResumeTemplateDefinition[];
      try {
        const results = [];
        for (const templateId of templateIds) {
          results.push(await restoreTemplateApi(templateId));
        }
        restoredItems = results.map((item) => item.template);
      } catch (error) {
        console.error("Failed to restore template.", error);
        if (!isApiErrorToastShown(error)) {
          toast.error(messages.loadError, { closeButton: true });
        }
        return false;
      }

      markRouteMutation();
      startTransition(() => {
        setDeletedTemplates((current) =>
          current.filter((item) => !templateIds.includes(item.id)),
        );
        setCustomTemplates((current) => [...restoredItems, ...current]);
      });
      toast.success(
        templateIds.length > 1
          ? messages.templatesRestored
          : messages.templateRestored,
        { closeButton: true },
      );
      return true;
    },
    [deletedTemplates, markRouteMutation, messages],
  );

  const permanentlyDeleteTemplates = useCallback(
    async (templateIds: string[]) => {
      if (templateIds.length === 0) {
        return false;
      }

      try {
        for (const templateId of templateIds) {
          await deleteTemplateForeverApi(templateId);
        }
      } catch (error) {
        console.error("Failed to permanently delete template.", error);
        if (!isApiErrorToastShown(error)) {
          toast.error(messages.loadError, { closeButton: true });
        }
        return false;
      }

      markRouteMutation();
      startTransition(() => {
        setDeletedTemplates((current) =>
          current.filter((item) => !templateIds.includes(item.id)),
        );
      });
      toast.success(
        templateIds.length > 1
          ? messages.templatesDeletedForever
          : messages.templateDeletedForever,
        { closeButton: true },
      );
      return true;
    },
    [markRouteMutation, messages],
  );

  return {
    changeTheme,
    deletedResumes,
    deletedTemplates,
    hasLoaded,
    hasLoadError,
    permanentlyDeleteResumes,
    permanentlyDeleteTemplates,
    resolvedTheme,
    routeData,
    restoreResumes,
    restoreTemplates,
    retryLoad: () => setRetryKey((current) => current + 1),
    templatePreviewResume,
    templates,
    theme,
  };
}
