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
import { createTemplatePreviewResume } from "@/lib/template-preview-resume";
import {
  createCustomTemplateFromBase,
  createTemplateLayout,
  createTemplateSettings,
  getTemplateCatalog,
} from "@/lib/templates";
import { runViewTransition } from "@/lib/view-transition";
import { createTemplateFingerprint } from "@/lib/workspace-change-tracking";
import type { WorkspacePreferencesPersistence } from "@/lib/workspace-preferences-persistence";
import {
  createTemplateApi,
  fetchWorkspaceRouteData,
  saveDefaultTemplateApi,
  saveUserSettingsApi,
} from "@/lib/workspace-api";
import {
  createTemplateDetailRouteHandoff,
  getTemplateDetailRouteHandoff,
  getTemplatePath,
  getWorkspacePath,
} from "@/lib/workspace-route";
import type {
  ResumeTemplateDefinition,
  ResumeTemplateImageElement,
  ThemeMode,
  WorkspaceView,
} from "@/types/resume";
import { useTemplateDetailLeave } from "@/components/workspace/use-template-detail-leave";
import { useTemplateDetailSave } from "@/components/workspace/use-template-detail-save";

interface TemplateDetailWorkspaceOptions {
  locale: Locale;
  messages: AppMessages;
  onLocaleChange: (locale: Locale) => void;
  onLogout: () => void;
  persistence: WorkspacePreferencesPersistence;
  routeState: unknown;
  templateId: string;
}

function normalizeWorkspaceTheme(value: unknown): ThemeMode {
  return value === "dark" || value === "system" ? value : "light";
}

function preloadWorkspaceView(view: WorkspaceView) {
  if (view === "models") {
    void import("@/components/workspace/models-workspace-page");
    return;
  }
  if (view === "settings") {
    void import("@/components/workspace/settings-workspace-page");
    return;
  }
  if (view === "templates") {
    void import("@/components/workspace/template-gallery-workspace-page");
    return;
  }
  if (view === "trash") {
    void import("@/components/workspace/trash-workspace-page");
    return;
  }

  void import("@/components/workspace/resume-gallery-workspace-page");
}

function resolveInitialTemplate(
  messages: AppMessages,
  routeState: unknown,
  templateId: string,
) {
  const handoff = getTemplateDetailRouteHandoff(routeState, templateId);
  if (!handoff) {
    return null;
  }

  const template = getTemplateCatalog(
    messages,
    handoff.data.customTemplates,
  ).find((item) => item.id === templateId);

  return template ? { data: handoff.data, template } : null;
}

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
  const initialLocaleRef = useRef(locale);
  const initialDetail = useMemo(
    () => resolveInitialTemplate(messages, routeState, templateId),
    [messages, routeState, templateId],
  );
  const initialPreferences = persistence.getSnapshot();
  const requestIdRef = useRef(0);
  const createInFlightRef = useRef(false);
  const setDefaultInFlightRef = useRef(false);
  const [retryKey, setRetryKey] = useState(0);
  const [hasLoaded, setHasLoaded] = useState(Boolean(initialDetail));
  const [hasLoadError, setHasLoadError] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [isCreating, setIsCreating] = useState(false);
  const [settingDefaultTemplateId, setSettingDefaultTemplateId] = useState<
    string | null
  >(null);
  const [theme, setTheme] = useState<ThemeMode>(() =>
    initialDetail?.data.theme
      ? normalizeWorkspaceTheme(initialDetail.data.theme)
      : initialPreferences?.theme ?? "light",
  );
  const [resolvedTheme, setResolvedTheme] = useState<"light" | "dark">(() =>
    document.documentElement.classList.contains("dark") ? "dark" : "light",
  );
  const [defaultTemplateId, setDefaultTemplateId] = useState(
    initialDetail?.data.defaultTemplateId ?? "minimal",
  );
  const [customTemplates, setCustomTemplates] = useState<
    ResumeTemplateDefinition[]
  >(initialDetail?.data.customTemplates ?? []);
  const calibrationFingerprintRef = useRef(
    createTemplateFingerprint(initialDetail?.template ?? null),
  );
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
  const templatePreviewResume = useDeferredValue(
    useMemo(() => createTemplatePreviewResume(messages), [messages]),
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
      void import("@/components/preview/document-preview-card");

      try {
        await persistence.flush();
        if (signal.aborted || requestIdRef.current !== requestId) {
          return;
        }

        const source = await fetchWorkspaceRouteData("template-detail", {
          notifyOnError: false,
          signal,
        });
        if (signal.aborted || requestIdRef.current !== requestId) {
          return;
        }

        const targetTemplate = getTemplateCatalog(
          messages,
          source.data.customTemplates,
        ).find((item) => item.id === templateId);
        if (!targetTemplate) {
          navigate("/templates", { replace: true });
          return;
        }

        const nextTheme = source.data.theme
          ? normalizeWorkspaceTheme(source.data.theme)
          : themeRef.current;
        const agentSettings =
          persistence.getSnapshot()?.agentSettings ??
          createDefaultAgentSettings();

        setTheme(nextTheme);
        setDefaultTemplateId(source.data.defaultTemplateId);
        const priorPersistedFingerprint = calibrationFingerprintRef.current;
        setCustomTemplates((current) => {
          const currentTarget = current.find((item) => item.id === templateId);
          if (
            !currentTarget ||
            createTemplateFingerprint(currentTarget) ===
              priorPersistedFingerprint
          ) {
            return source.data.customTemplates;
          }

          // The handoff made this draft editable before calibration finished.
          // Merge server catalog metadata without replacing a newer local edit.
          return source.data.customTemplates.map((item) =>
            item.id === templateId ? currentTarget : item,
          );
        });
        hydratePersistedTemplate(targetTemplate);
        calibrationFingerprintRef.current =
          createTemplateFingerprint(targetTemplate);
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
      navigate,
      persistence,
      hydratePersistedTemplate,
      templateId,
    ],
  );

  useEffect(() => {
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
  }, [loadRouteData, retryKey]);

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

    const draftTemplate = createCustomTemplateFromBase(template, {
      name: `${messages.customTemplate} ${customTemplates.length + 1}`,
    });
    createInFlightRef.current = true;
    setIsCreating(true);
    try {
      await save();
      const result = await createTemplateApi(draftTemplate);
      const nextCustomTemplates = [...customTemplates, result.template];

      setCustomTemplates((current) => [...current, result.template]);
      adoptPersistedTemplate(result.template);
      runViewTransition(
        () =>
          navigate(getTemplatePath(result.template.id), {
            state: createTemplateDetailRouteHandoff(result.template.id, {
              customTemplates: nextCustomTemplates,
              defaultTemplateId,
              theme,
            }),
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
    customTemplates,
    defaultTemplateId,
    isLoading,
    messages,
    navigate,
    adoptPersistedTemplate,
    save,
    saveState,
    template,
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
        const result = await saveDefaultTemplateApi(targetId);
        setDefaultTemplateId(result.defaultTemplateId);
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
    [defaultTemplateId, messages, templateCatalog],
  );

  const leave = useTemplateDetailLeave({
    discard,
    hasUnsavedChanges,
    messages,
    save,
  });
  const { requestLeave } = leave;
  const changeView = useCallback(
    (view: WorkspaceView) =>
      requestLeave(() => {
        preloadWorkspaceView(view);
        navigate(getWorkspacePath(view));
      }),
    [navigate, requestLeave],
  );
  const goBack = useCallback(
    () =>
      requestLeave(() =>
        runViewTransition(() => navigate("/templates"), "nav-back"),
      ),
    [navigate, requestLeave],
  );
  const logout = useCallback(
    () => requestLeave(onLogout),
    [onLogout, requestLeave],
  );

  return {
    changeTheme,
    changeView,
    createCustomTemplate,
    defaultTemplateId,
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
    template,
    templatePreviewResume,
    theme,
    updateTemplate,
  };
}

export type TemplateDetailWorkspaceController = ReturnType<
  typeof useTemplateDetailWorkspace
>;
