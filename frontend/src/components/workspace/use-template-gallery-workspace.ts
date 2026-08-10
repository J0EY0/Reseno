import {
  useCallback,
  useDeferredValue,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";

import { getMessagesSync, type AppMessages, type Locale } from "@/i18n";
import { createDefaultAgentSettings } from "@/lib/agent-settings";
import { isAbortError, isApiErrorToastShown } from "@/lib/api-client";
import { importTemplatePayload } from "@/lib/import-api";
import { createTemplatePreviewResume } from "@/lib/template-preview-resume";
import { useWorkspaceLateralRouteData } from "@/components/workspace/use-workspace-lateral-route-data";
import {
  createCustomTemplateFromBase,
  getTemplateById,
  getTemplateCatalog,
} from "@/lib/templates";
import { runViewTransition } from "@/lib/view-transition";
import type { WorkspacePreferencesPersistence } from "@/lib/workspace-preferences-persistence";
import {
  createTemplateApi,
  fetchWorkspaceRouteData,
  moveTemplateToTrashApi,
  saveDefaultTemplateApi,
  saveUserSettingsApi,
} from "@/lib/workspace-api";
import {
  createTemplateDetailRouteHandoff,
  getTemplatePath,
} from "@/lib/workspace-route";
import type {
  ResumeTemplateDefinition,
  ResumeTemplateId,
  ThemeMode,
} from "@/types/resume";

const baseTemplateId: ResumeTemplateId = "minimal";

function preloadTemplateDetailWorkspace() {
  return Promise.all([
    import("@/components/workspace/template-detail-workspace-page"),
    import("@/components/preview/document-preview-card"),
  ]);
}

function normalizeWorkspaceTheme(value: unknown): ThemeMode {
  return value === "dark" || value === "system" ? value : "light";
}

export function useTemplateGalleryWorkspace({
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
  const navigate = useNavigate();
  const preparedRouteData = useWorkspaceLateralRouteData("templates");
  const initialLocaleRef = useRef(locale);
  const requestIdRef = useRef(0);
  const routeMutationEpochRef = useRef(0);
  const createInFlightRef = useRef(false);
  const importInFlightRef = useRef(false);
  const setDefaultInFlightRef = useRef(false);
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
  const [isCreating, setIsCreating] = useState(false);
  const [isImporting, setIsImporting] = useState(false);
  const [settingDefaultTemplateId, setSettingDefaultTemplateId] = useState<
    string | null
  >(null);
  const [defaultTemplateId, setDefaultTemplateId] =
    useState<ResumeTemplateId>(
      () => preparedRouteData?.defaultTemplateId ?? baseTemplateId,
    );
  const [customTemplates, setCustomTemplates] = useState<
    ResumeTemplateDefinition[]
  >(() => preparedRouteData?.customTemplates ?? []);
  const templateCatalog = useMemo(
    () => getTemplateCatalog(messages, customTemplates),
    [customTemplates, messages],
  );
  const routeData = useMemo(
    () => ({ customTemplates, defaultTemplateId, theme }),
    [customTemplates, defaultTemplateId, theme],
  );
  const previewResume = useDeferredValue(
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
              "template-gallery",
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
            setDefaultTemplateId(source.data.defaultTemplateId);
            setCustomTemplates(source.data.customTemplates);
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

            console.error("Failed to load the template gallery route.", error);
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
    // then abort any real in-flight request when route ownership changes.
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

  const buildTemplateDetailHandoff = useCallback(
    (
      templateId: string,
      nextCustomTemplates: ResumeTemplateDefinition[] = customTemplates,
    ) =>
      createTemplateDetailRouteHandoff(templateId, {
        customTemplates: nextCustomTemplates,
        defaultTemplateId,
        theme,
      }),
    [customTemplates, defaultTemplateId, theme],
  );

  const openTemplate = useCallback(
    async (templateId: string) => {
      if (!templateCatalog.some((item) => item.id === templateId)) {
        return;
      }

      try {
        // This is a cold cross-route navigation. Resolve the detail route and
        // its two lazy presentation seams before starting the view transition.
        await preloadTemplateDetailWorkspace();
      } catch (error) {
        console.error("Failed to preload the template detail route.", error);
        toast.error(messages.loadError, { closeButton: true });
        return;
      }

      runViewTransition(
        () =>
          navigate(getTemplatePath(templateId), {
            state: buildTemplateDetailHandoff(templateId),
          }),
        "nav-forward",
      );
    },
    [buildTemplateDetailHandoff, messages.loadError, navigate, templateCatalog],
  );

  const createCustomTemplate = useCallback(async () => {
    if (isLoading || createInFlightRef.current) {
      return;
    }

    createInFlightRef.current = true;
    setIsCreating(true);
    void preloadTemplateDetailWorkspace().catch((error) => {
      console.warn("Failed to warm the template detail route.", error);
    });
    const sourceTemplate = getTemplateById(templateCatalog, baseTemplateId);
    const draftTemplate = createCustomTemplateFromBase(sourceTemplate, {
      name: `${messages.customTemplate} ${customTemplates.length + 1}`,
    });

    try {
      const result = await createTemplateApi(draftTemplate);
      const nextCustomTemplates = [...customTemplates, result.template];
      markRouteMutation();
      setCustomTemplates(nextCustomTemplates);
      runViewTransition(
        () =>
          navigate(getTemplatePath(result.template.id), {
            state: buildTemplateDetailHandoff(
              result.template.id,
              nextCustomTemplates,
            ),
          }),
        "nav-forward",
      );
      toast.success(messages.templateCreated, { closeButton: true });
    } catch (error) {
      console.error("Failed to create template in backend.", error);
      if (!isApiErrorToastShown(error)) {
        toast.error(messages.loadError, { closeButton: true });
      }
    } finally {
      createInFlightRef.current = false;
      setIsCreating(false);
    }
  }, [
    buildTemplateDetailHandoff,
    customTemplates,
    isLoading,
    markRouteMutation,
    messages,
    navigate,
    templateCatalog,
  ]);

  const importTemplates = useCallback(
    async (file: File) => {
      if (importInFlightRef.current) {
        return;
      }

      importInFlightRef.current = true;
      setIsImporting(true);
      void preloadTemplateDetailWorkspace().catch((error) => {
        console.warn("Failed to warm the template detail route.", error);
      });

      try {
        const payload = await importTemplatePayload(file);
        if (payload.templates.length === 0) {
          throw new Error("No valid templates found in imported file.");
        }

        const savedImports: ResumeTemplateDefinition[] = [];
        for (const item of payload.templates) {
          const result = await createTemplateApi(item);
          savedImports.push(result.template);
        }

        const firstImportedTemplate = savedImports[0];
        if (!firstImportedTemplate) {
          throw new Error("Failed to save imported template.");
        }

        const nextCustomTemplates = [...customTemplates, ...savedImports];
        markRouteMutation();
        setCustomTemplates(nextCustomTemplates);
        runViewTransition(
          () =>
            navigate(getTemplatePath(firstImportedTemplate.id), {
              state: buildTemplateDetailHandoff(
                firstImportedTemplate.id,
                nextCustomTemplates,
              ),
            }),
          "nav-forward",
        );
        toast.success(messages.templateImported, { closeButton: true });
      } catch (error) {
        console.error("Failed to import template JSON.", error);
        if (!isApiErrorToastShown(error)) {
          toast.error(messages.templateImportFailed, { closeButton: true });
        }
      } finally {
        importInFlightRef.current = false;
        setIsImporting(false);
      }
    },
    [buildTemplateDetailHandoff, customTemplates, markRouteMutation, messages, navigate],
  );

  const deleteTemplates = useCallback(
    async (templateIds: string[]) => {
      const customTemplateIds = templateIds.filter((templateId) =>
        customTemplates.some((item) => item.id === templateId),
      );
      if (customTemplateIds.length === 0) {
        return;
      }

      try {
        for (const templateId of customTemplateIds) {
          await moveTemplateToTrashApi(templateId);
        }
      } catch (error) {
        console.error("Failed to move template to trash.", error);
        if (!isApiErrorToastShown(error)) {
          toast.error(messages.loadError, { closeButton: true });
        }
        return;
      }

      markRouteMutation();
      setCustomTemplates((current) =>
        current.filter((item) => !customTemplateIds.includes(item.id)),
      );
      if (customTemplateIds.includes(defaultTemplateId)) {
        setDefaultTemplateId(baseTemplateId);
      }
      toast.success(
        customTemplateIds.length > 1
          ? messages.templatesDeleted
          : messages.templateDeleted,
        { closeButton: true },
      );
    },
    [customTemplates, defaultTemplateId, markRouteMutation, messages],
  );

  const setDefaultTemplate = useCallback(
    async (templateId: string) => {
      if (
        templateId === defaultTemplateId ||
        setDefaultInFlightRef.current ||
        !templateCatalog.some((item) => item.id === templateId)
      ) {
        return;
      }

      setDefaultInFlightRef.current = true;
      setSettingDefaultTemplateId(templateId);
      try {
        const result = await saveDefaultTemplateApi(templateId);
        markRouteMutation();
        setDefaultTemplateId(result.defaultTemplateId);
        toast.success(messages.defaultTemplateUpdated, { closeButton: true });
      } catch (error) {
        console.error("Failed to update default template.", error);
        if (!isApiErrorToastShown(error)) {
          toast.error(messages.loadError, { closeButton: true });
        }
      } finally {
        setDefaultInFlightRef.current = false;
        setSettingDefaultTemplateId(null);
      }
    },
    [defaultTemplateId, markRouteMutation, messages, templateCatalog],
  );

  return {
    changeTheme,
    createCustomTemplate,
    defaultTemplateId,
    deleteTemplates,
    hasLoaded,
    hasLoadError,
    importTemplates,
    isCreating,
    isImporting,
    openTemplate,
    previewResume,
    retryLoad: () => setRetryKey((current) => current + 1),
    resolvedTheme,
    routeData,
    setDefaultTemplate,
    settingDefaultTemplateId,
    templateCatalog,
    theme,
  };
}
