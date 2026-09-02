import {
  startTransition,
  useCallback,
  useDeferredValue,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";

import { loadDocumentPreviewCard } from "@/components/preview/document-preview-card-loader";
import { resolveInitialTemplateDetail } from "@/components/workspace/template-detail-initial-route";
import { loadTemplateDetailRouteData } from "@/components/workspace/workspace-route-preparation";
import { getMessagesSync, type AppMessages, type Locale } from "@/i18n";
import { useLocalizedMessages } from "@/i18n/use-localized-messages";
import { createDefaultAgentSettings } from "@/lib/agent-settings";
import { isAbortError, isApiErrorToastShown } from "@/lib/api-client";
import {
  createTemplatePreviewResumes,
  getTemplatePreviewResume,
} from "@/lib/template-preview-resume";
import {
  createCustomTemplateFromBase,
  createTemplateLayout,
  createTemplateSettings,
  getTemplateCatalog,
} from "@/lib/templates";
import { createTemplateFingerprint } from "@/lib/workspace-change-tracking";
import type { WorkspacePreferencesPersistence } from "@/lib/workspace-preferences-persistence";
import {
  loadWorkspaceThemePreference,
  normalizeWorkspaceTheme,
} from "@/lib/workspace-theme";
import {
  createTemplateApi,
  saveDefaultTemplateApi,
  saveUserSettingsApi,
} from "@/lib/workspace-api";
import {
  createTemplateDetailRouteHandoff,
  getTemplatePath,
} from "@/lib/workspace-route";
import type {
  DefaultTemplateIds,
  DocumentLocale,
  ResumeTemplateDefinition,
  ResumeTemplateImageElement,
  ThemeMode,
  WorkspaceView,
} from "@/types/resume";
import { useTemplateDetailLeave } from "@/components/workspace/use-template-detail-leave";
import { useTemplateDetailSave } from "@/components/workspace/use-template-detail-save";
import { usePreparedWorkspaceNavigation } from "@/components/workspace/use-prepared-workspace-navigation";
import { useWorkspaceNavigationTransaction } from "@/components/workspace/use-workspace-navigation-transaction";

interface TemplateDetailWorkspaceOptions {
  locale: Locale;
  messages: AppMessages;
  onLocaleChange: (locale: Locale) => void;
  onLogout: () => void;
  persistence: WorkspacePreferencesPersistence;
  routeState: unknown;
  templateId: string;
}

const initialDefaultTemplateIds: DefaultTemplateIds = {
  zh: "minimal",
  en: "minimal",
};

/** Owns only the /template/:id route data, draft, and route commands. */
export function useTemplateDetailWorkspace({
  locale,
  messages,
  onLocaleChange,
  onLogout,
  persistence,
  routeState,
  templateId,
}: TemplateDetailWorkspaceOptions) {
  const navigate = useNavigate();
  const { beginNavigation } = useWorkspaceNavigationTransaction();
  const initialLocaleRef = useRef(locale);
  const initialDetail = useMemo(
    () => resolveInitialTemplateDetail(messages, routeState, templateId),
    [messages, routeState, templateId],
  );
  const initialPreferences = persistence.getSnapshot();
  const requestIdRef = useRef(0);
  const createInFlightRef = useRef(false);
  const setDefaultInFlightRef = useRef(false);
  const [retryKey, setRetryKey] = useState(0);
  const [hasLoaded, setHasLoaded] = useState(Boolean(initialDetail));
  const [hasLoadError, setHasLoadError] = useState(false);
  const [isLoading, setIsLoading] = useState(!initialDetail);
  const [isCreating, setIsCreating] = useState(false);
  const [templateLocale, setTemplateLocale] = useState<DocumentLocale>(
    () => initialDetail?.templateLocale ?? locale,
  );
  const [settingDefaultTemplateId, setSettingDefaultTemplateId] = useState<
    string | null
  >(null);
  const [theme, setTheme] = useState<ThemeMode>(() =>
    initialDetail?.data.theme
      ? normalizeWorkspaceTheme(initialDetail.data.theme)
      : initialPreferences?.theme ?? loadWorkspaceThemePreference(),
  );
  const [resolvedTheme, setResolvedTheme] = useState<"light" | "dark">(() =>
    document.documentElement.classList.contains("dark") ? "dark" : "light",
  );
  const [defaultTemplateIds, setDefaultTemplateIds] =
    useState<DefaultTemplateIds>(
      () =>
        initialDetail?.data.defaultTemplateIds ?? initialDefaultTemplateIds,
    );
  const [customTemplates, setCustomTemplates] = useState<
    ResumeTemplateDefinition[]
  >(initialDetail?.data.customTemplates ?? []);
  const themeRef = useRef(theme);
  themeRef.current = theme;

  const templateCatalog = useMemo(
    () => getTemplateCatalog(messages, customTemplates),
    [customTemplates, messages],
  );
  const template = useMemo(
    () => templateCatalog.find((item) => item.id === templateId) ?? null,
    [templateCatalog, templateId],
  );
  const templatePreviewMessages = useLocalizedMessages(templateLocale);
  const templatePreviewResumes = useMemo(
    () =>
      templatePreviewMessages
        ? createTemplatePreviewResumes(templatePreviewMessages)
        : null,
    [templatePreviewMessages],
  );
  const templatePreviewResume = useDeferredValue(
    template && templatePreviewResumes
      ? getTemplatePreviewResume(templatePreviewResumes, template)
      : null,
  );

  const adoptSavedTemplate = useCallback(
    (
      savedTemplate: ResumeTemplateDefinition,
      acceptedFingerprints: ReadonlySet<string>,
    ) => {
      setCustomTemplates((current) =>
        current.map((item) => {
          if (item.id !== savedTemplate.id) {
            return item;
          }

          const currentFingerprint = createTemplateFingerprint(item);
          return acceptedFingerprints.has(currentFingerprint)
            ? savedTemplate
            : item;
        }),
      );
    },
    [],
  );
  const restoreTemplate = useCallback(
    (persistedTemplate: ResumeTemplateDefinition) => {
      setCustomTemplates((current) =>
        current.map((item) =>
          item.id === persistedTemplate.id ? persistedTemplate : item,
        ),
      );
    },
    [],
  );
  const {
    adoptPersistedTemplate,
    changeCount: saveChangeCount,
    discard,
    hasUnsavedChanges,
    hydratePersistedTemplate,
    lastSavedAt: saveLastSavedAt,
    save,
    saveState,
  } = useTemplateDetailSave({
    isLoading,
    messages,
    onAdoptSavedTemplate: adoptSavedTemplate,
    onRestoreTemplate: restoreTemplate,
    template,
  });

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
      void loadDocumentPreviewCard();

      try {
        const routeData = await loadTemplateDetailRouteData(
          templateId,
          persistence,
          { signal },
        );
        if (signal.aborted || requestIdRef.current !== requestId) {
          return;
        }

        const targetTemplate = getTemplateCatalog(
          messages,
          routeData.customTemplates,
        ).find((item) => item.id === templateId);
        if (!targetTemplate) {
          throw new Error("Template target is unavailable.");
        }

        const nextTheme = routeData.theme
          ? normalizeWorkspaceTheme(routeData.theme)
          : themeRef.current;
        const agentSettings =
          persistence.getSnapshot()?.agentSettings ??
          createDefaultAgentSettings();

        setTheme(nextTheme);
        setDefaultTemplateIds(routeData.defaultTemplateIds);
        setCustomTemplates(routeData.customTemplates);
        hydratePersistedTemplate(targetTemplate);
        persistence.hydrate({
          agentSettings,
          locale: initialLocaleRef.current,
          theme: nextTheme,
        });
        setHasLoaded(true);
      } catch (error) {
        if (isAbortError(error) || requestIdRef.current !== requestId) {
          return;
        }
        console.error("Failed to load the template detail route.", error);
        if (!isApiErrorToastShown(error)) {
          toast.error(
            getMessagesSync(initialLocaleRef.current).apiMessages
              .REQUEST_FAILED,
            { closeButton: true, id: "workspace-load-error" },
          );
        }
        setHasLoadError(true);
      } finally {
        if (requestIdRef.current === requestId) {
          setIsLoading(false);
        }
      }
    },
    [
      messages,
      persistence,
      hydratePersistedTemplate,
      templateId,
    ],
  );

  useEffect(() => {
    if (initialDetail && retryKey === 0) {
      persistence.hydrate({
        agentSettings:
          persistence.getSnapshot()?.agentSettings ??
          createDefaultAgentSettings(),
        locale: initialLocaleRef.current,
        theme: initialDetail.data.theme
          ? normalizeWorkspaceTheme(initialDetail.data.theme)
          : themeRef.current,
      });
      setHasLoaded(true);
      setHasLoadError(false);
      setIsLoading(false);
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
  }, [initialDetail, loadRouteData, persistence, retryKey]);

  const changeTheme = useCallback(
    (nextTheme: ThemeMode) => {
      setTheme(nextTheme);
      if (!hasLoaded || isLoading) {
        return;
      }

      const snapshot = {
        agentSettings:
          persistence.getSnapshot()?.agentSettings ??
          createDefaultAgentSettings(),
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
          },
        },
      );
    },
    [
      hasLoaded,
      isLoading,
      locale,
      messages.loadError,
      onLocaleChange,
      persistence,
    ],
  );

  const createCustomTemplate = useCallback(async () => {
    if (
      !template ||
      isLoading ||
      saveState === "saving" ||
      createInFlightRef.current
    ) {
      return;
    }

    const intent = beginNavigation();
    const draftTemplate = createCustomTemplateFromBase(template, {
      name: `${messages.customTemplate} ${customTemplates.length + 1}`,
    });
    createInFlightRef.current = true;
    setIsCreating(true);
    try {
      await save();
      if (!intent.isCurrent()) {
        return;
      }

      const result = await createTemplateApi(draftTemplate);
      const nextCustomTemplates = [...customTemplates, result.template];
      setCustomTemplates((current) => [...current, result.template]);
      if (!intent.isCurrent()) {
        return;
      }

      adoptPersistedTemplate(result.template);
      startTransition(() => {
        if (!intent.isCurrent()) {
          return;
        }
        intent.finish();
        navigate(getTemplatePath(result.template.id), {
          state: createTemplateDetailRouteHandoff(result.template.id, {
            customTemplates: nextCustomTemplates,
            defaultTemplateIds,
            theme,
          }, templateLocale),
        });
      });
      toast.success(messages.templateCreated, { closeButton: true });
    } catch (error) {
      if (intent.isCurrent()) {
        intent.finish();
      }
      console.error("Failed to create template in backend.", error);
      if (!isApiErrorToastShown(error)) {
        toast.error(messages.loadError, { closeButton: true });
      }
    } finally {
      createInFlightRef.current = false;
      setIsCreating(false);
    }
  }, [
    beginNavigation,
    customTemplates,
    defaultTemplateIds,
    isLoading,
    messages,
    navigate,
    adoptPersistedTemplate,
    save,
    saveState,
    template,
    templateLocale,
    theme,
  ]);

  const updateTemplate = useCallback(
    (targetId: string, patch: Partial<ResumeTemplateDefinition>) => {
      setCustomTemplates((current) =>
        current.map((item) =>
          item.id === targetId
            ? {
                ...item,
                ...patch,
                layout: patch.layout
                  ? patch.preset
                    ? createTemplateLayout(patch.preset, patch.layout)
                    : patch.layout
                  : patch.preset
                    ? createTemplateLayout(patch.preset)
                    : item.layout,
                settings: patch.settings
                  ? patch.preset
                    ? createTemplateSettings(patch.preset, patch.settings)
                    : patch.settings
                  : patch.preset
                    ? createTemplateSettings(patch.preset)
                    : item.settings,
                updatedAt: new Date().toISOString(),
              }
            : item,
        ),
      );
    },
    [],
  );

  const moveTemplateImage = useCallback(
    (
      imageId: string,
      patch: Pick<ResumeTemplateImageElement, "x" | "y">,
    ) => {
      if (!template || template.isBuiltIn) {
        return;
      }
      updateTemplate(template.id, {
        layout: {
          ...template.layout,
          images: template.layout.images.map((image) =>
            image.id === imageId ? { ...image, ...patch } : image,
          ),
        },
      });
    },
    [template, updateTemplate],
  );

  const setDefaultTemplate = useCallback(
    async (targetId: string) => {
      const defaultTemplateId = defaultTemplateIds[templateLocale];
      if (
        targetId === defaultTemplateId ||
        setDefaultInFlightRef.current ||
        !templateCatalog.some((item) => item.id === targetId)
      ) {
        return;
      }

      setDefaultInFlightRef.current = true;
      setSettingDefaultTemplateId(targetId);
      try {
        const result = await saveDefaultTemplateApi(templateLocale, targetId);
        setDefaultTemplateIds(result.defaultTemplateIds);
        toast.success(messages.defaultTemplateUpdated, { closeButton: true });
      } catch (error) {
        console.error("Failed to update the default template.", error);
        if (!isApiErrorToastShown(error)) {
          toast.error(messages.loadError, { closeButton: true });
        }
      } finally {
        setDefaultInFlightRef.current = false;
        setSettingDefaultTemplateId(null);
      }
    },
    [defaultTemplateIds, messages, templateCatalog, templateLocale],
  );

  const leave = useTemplateDetailLeave({
    discard,
    hasUnsavedChanges,
    messages,
    save,
  });
  const { requestLeave } = leave;
  const {
    preload: preloadWorkspaceView,
    request: requestWorkspaceNavigation,
  } = usePreparedWorkspaceNavigation({
    persistence,
    preparationErrorMessage: messages.loadError,
    requestLeave,
    requiresLeaveResolution: hasUnsavedChanges,
  });
  const changeView = useCallback(
    (view: WorkspaceView) => {
      void requestWorkspaceNavigation(view);
    },
    [requestWorkspaceNavigation],
  );
  const goBack = useCallback(
    () => {
      void requestWorkspaceNavigation("templates");
    },
    [requestWorkspaceNavigation],
  );
  const logout = useCallback(
    () => {
      const intent = beginNavigation();
      requestLeave(
        () => {
          if (!intent.isCurrent()) {
            return;
          }
          intent.finish();
          onLogout();
        },
        intent.cancel,
      );
    },
    [beginNavigation, onLogout, requestLeave],
  );

  return {
    changeTheme,
    changeView,
    createCustomTemplate,
    defaultTemplateId: defaultTemplateIds[templateLocale],
    goBack,
    hasLoadError,
    hasLoaded,
    isCreating,
    isLoading,
    leave,
    logout,
    moveTemplateImage,
    preloadWorkspaceView,
    resolvedTheme,
    retryLoad: () => setRetryKey((current) => current + 1),
    save,
    saveChangeCount,
    saveLastSavedAt,
    saveState,
    setDefaultTemplate,
    settingDefaultTemplateId,
    setTemplateLocale,
    template,
    templateLocale,
    templatePreviewMessages,
    templatePreviewResume,
    theme,
    updateTemplate,
  };
}

export type TemplateDetailWorkspaceController = ReturnType<
  typeof useTemplateDetailWorkspace
>;
