import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";

import { getMessagesSync, type AppMessages, type Locale } from "@/i18n";
import { createDefaultAgentSettings } from "@/lib/agent-settings";
import { isAbortError, isApiErrorToastShown } from "@/lib/api-client";
import { createDefaultResumeTitle } from "@/lib/resume-title";
import { getTemplateCatalog } from "@/lib/templates";
import { runViewTransition } from "@/lib/view-transition";
import type { WorkspacePreferencesPersistence } from "@/lib/workspace-preferences-persistence";
import { importResumesIntoWorkspace } from "@/components/workspace/resume-gallery-import";
import { useWorkspaceLateralRouteData } from "@/components/workspace/use-workspace-lateral-route-data";
import {
  prepareCreatedResumeDetailRoute,
  prepareResumeDetailRoute,
  preloadResumeDetailRoute,
  WORKSPACE_NAVIGATION_ERROR_TOAST_ID,
} from "@/components/workspace/workspace-route-preparation";
import {
  useWorkspaceNavigationTransaction,
  type WorkspaceNavigationIntent,
} from "@/components/workspace/use-workspace-navigation-transaction";
import {
  createResumeApi,
  fetchWorkspaceRouteData,
  moveResumeToTrashApi,
  saveUserSettingsApi,
} from "@/lib/workspace-api";
import {
  createResumeDetailRouteHandoff,
  getResumePath,
} from "@/lib/workspace-route";
import type {
  ResumeTemplateDefinition,
  ResumeTemplateId,
  ResumeWorkspaceItem,
  ThemeMode,
} from "@/types/resume";
import type { PreparedResumeDetailRouteData } from "@/lib/workspace-route-data";

const defaultTemplateId: ResumeTemplateId = "minimal";

function normalizeWorkspaceTheme(value: unknown): ThemeMode {
  return value === "dark" || value === "system" ? value : "light";
}

export function useResumeGalleryWorkspace({
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
  const preparedRouteData = useWorkspaceLateralRouteData("resume");
  const initialLocaleRef = useRef(locale);
  const requestIdRef = useRef(0);
  const createInFlightRef = useRef(false);
  const importInFlightRef = useRef(false);
  const { beginNavigation } = useWorkspaceNavigationTransaction();
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
  const [resumes, setResumes] = useState<ResumeWorkspaceItem[]>(
    () => preparedRouteData?.resumes ?? [],
  );
  const [activeDefaultTemplateId, setActiveDefaultTemplateId] =
    useState<ResumeTemplateId>(
      () => preparedRouteData?.defaultTemplateId ?? defaultTemplateId,
    );
  const [customTemplates, setCustomTemplates] = useState<
    ResumeTemplateDefinition[]
  >(() => preparedRouteData?.customTemplates ?? []);
  const templateCatalog = useMemo(
    () => getTemplateCatalog(messages, customTemplates),
    [customTemplates, messages],
  );
  const routeData = useMemo(
    () => ({
      customTemplates,
      defaultTemplateId: activeDefaultTemplateId,
      resumes,
      theme,
    }),
    [activeDefaultTemplateId, customTemplates, resumes, theme],
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
        await persistence.flush();
        if (signal.aborted || requestIdRef.current !== requestId) {
          return;
        }

        const source = await fetchWorkspaceRouteData("resume-gallery", {
          notifyOnError: false,
          signal,
        });
        if (signal.aborted || requestIdRef.current !== requestId) {
          return;
        }

        const persistedPreferences = persistence.getSnapshot();
        const nextTheme = source.data.theme
          ? normalizeWorkspaceTheme(source.data.theme)
          : persistedPreferences?.theme ?? "light";

        setTheme(nextTheme);
        setResumes(source.data.resumes);
        setActiveDefaultTemplateId(source.data.defaultTemplateId);
        setCustomTemplates(source.data.customTemplates);
        persistence.hydrate({
          locale: initialLocaleRef.current,
          theme: nextTheme,
          agentSettings:
            persistedPreferences?.agentSettings ?? createDefaultAgentSettings(),
        });
        setHasLoaded(true);
      } catch (error) {
        if (
          signal.aborted ||
          isAbortError(error) ||
          requestIdRef.current !== requestId
        ) {
          return;
        }

        console.error("Failed to load the resume gallery route.", error);
        if (!isApiErrorToastShown(error)) {
          toast.error(
            getMessagesSync(initialLocaleRef.current).apiMessages.REQUEST_FAILED,
            { closeButton: true, id: "workspace-load-error" },
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
    [persistence],
  );

  useEffect(() => {
    if (preparedRouteData && retryKey === 0) {
      const persistedPreferences = persistence.getSnapshot();
      persistence.hydrate({
        locale: initialLocaleRef.current,
        theme: preparedRouteData.theme
          ? normalizeWorkspaceTheme(preparedRouteData.theme)
          : persistedPreferences?.theme ?? "light",
        agentSettings:
          persistedPreferences?.agentSettings ?? createDefaultAgentSettings(),
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
  }, [loadRouteData, persistence, preparedRouteData, retryKey]);

  const changeTheme = useCallback(
    (nextTheme: ThemeMode) => {
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
    [hasLoaded, isLoading, locale, messages.loadError, onLocaleChange, persistence],
  );

  const buildResumeDetailHandoff = useCallback(
    (
      prepared: PreparedResumeDetailRouteData,
      resumeOrdinal: number,
      resumeCount: number,
    ) =>
      createResumeDetailRouteHandoff(
        prepared,
        resumeOrdinal,
        resumeCount,
      ),
    [],
  );

  const commitResumeDetailNavigation = useCallback(
    (
      intent: WorkspaceNavigationIntent,
      prepared: PreparedResumeDetailRouteData,
      resumeId: string,
      resumeOrdinal: number,
      resumeCount: number,
    ) => {
      if (!intent.isCurrent()) {
        return;
      }

      runViewTransition(() => {
        if (!intent.isCurrent()) {
          return;
        }
        intent.finish();
        navigate(getResumePath(resumeId), {
          state: buildResumeDetailHandoff(
            prepared,
            resumeOrdinal,
            resumeCount,
          ),
        });
      }, "nav-forward");
    },
    [buildResumeDetailHandoff, navigate],
  );

  const openResume = useCallback(
    async (resumeId: string) => {
      const intent = beginNavigation();
      const targetIndex = resumes.findIndex((item) => item.id === resumeId);
      const targetResume = resumes[targetIndex];
      if (!targetResume) {
        intent.finish();
        return;
      }

      toast.dismiss(WORKSPACE_NAVIGATION_ERROR_TOAST_ID);
      let prepared: PreparedResumeDetailRouteData;
      try {
        prepared = await prepareResumeDetailRoute(resumeId, persistence, {
          signal: intent.signal,
        });
      } catch (error) {
        if (
          intent.signal.aborted ||
          isAbortError(error) ||
          !intent.isCurrent()
        ) {
          return;
        }
        intent.finish();
        console.error("Failed to prepare the resume detail route.", error);
        toast.error(messages.loadError, {
          closeButton: true,
          id: WORKSPACE_NAVIGATION_ERROR_TOAST_ID,
        });
        return;
      }

      commitResumeDetailNavigation(
        intent,
        prepared,
        resumeId,
        targetIndex + 1,
        resumes.length,
      );
    },
    [
      beginNavigation,
      commitResumeDetailNavigation,
      messages.loadError,
      persistence,
      resumes,
    ],
  );

  const createResume = useCallback(async () => {
    if (isLoading || createInFlightRef.current) {
      return;
    }

    const intent = beginNavigation();
    createInFlightRef.current = true;
    setIsCreating(true);
    void preloadResumeDetailRoute().catch((error) => {
      console.warn("Failed to warm the resume detail route.", error);
    });

    try {
      const result = await createResumeApi({
        title: createDefaultResumeTitle(messages, resumes.length + 1),
        template: activeDefaultTemplateId,
      });
      setResumes((current) => [...current, result.resume]);
      if (!intent.isCurrent()) {
        return;
      }

      let prepared: PreparedResumeDetailRouteData;
      try {
        prepared = await prepareCreatedResumeDetailRoute(
          result,
          persistence,
          { signal: intent.signal },
        );
      } catch (error) {
        if (
          intent.signal.aborted ||
          isAbortError(error) ||
          !intent.isCurrent()
        ) {
          return;
        }
        intent.finish();
        console.error("Failed to prepare the created resume route.", error);
        toast.error(messages.loadError, {
          closeButton: true,
          id: WORKSPACE_NAVIGATION_ERROR_TOAST_ID,
        });
        return;
      }
      commitResumeDetailNavigation(
        intent,
        prepared,
        result.resume.id,
        resumes.length + 1,
        resumes.length + 1,
      );
    } catch (error) {
      if (intent.isCurrent()) {
        intent.finish();
      }
      console.error("Failed to create resume in backend.", error);
      if (!isApiErrorToastShown(error)) {
        toast.error(messages.loadError, { closeButton: true });
      }
    } finally {
      createInFlightRef.current = false;
      setIsCreating(false);
    }
  }, [
    activeDefaultTemplateId,
    beginNavigation,
    commitResumeDetailNavigation,
    isLoading,
    messages,
    persistence,
    resumes.length,
  ]);

  const importResume = useCallback(
    async (file: File) => {
      if (importInFlightRef.current) {
        return;
      }

      const intent = beginNavigation();
      importInFlightRef.current = true;
      setIsImporting(true);
      void preloadResumeDetailRoute().catch((error) => {
        console.warn("Failed to warm the resume detail route.", error);
      });

      try {
        const { savedImports, savedTemplates } =
          await importResumesIntoWorkspace(file, {
            defaultTemplateId: activeDefaultTemplateId,
            fallbackResumeTitle: createDefaultResumeTitle(
              messages,
              resumes.length + 1,
            ),
            fallbackSectionTitle: messages.importedResumeFallbackSection,
          });

        const firstSavedImport = savedImports[0];
        if (!firstSavedImport) {
          throw new Error("Failed to save imported resume.");
        }

        const nextCustomTemplates = [...customTemplates, ...savedTemplates];
        setResumes((current) => [
          ...current,
          ...savedImports.map((item) => item.resume),
        ]);
        if (savedTemplates.length > 0) {
          setCustomTemplates(nextCustomTemplates);
        }
        if (!intent.isCurrent()) {
          return;
        }

        let prepared: PreparedResumeDetailRouteData;
        try {
          prepared = await prepareCreatedResumeDetailRoute(
            firstSavedImport,
            persistence,
            { signal: intent.signal },
          );
        } catch (error) {
          if (
            intent.signal.aborted ||
            isAbortError(error) ||
            !intent.isCurrent()
          ) {
            return;
          }
          intent.finish();
          console.error("Failed to prepare the imported resume route.", error);
          toast.error(messages.loadError, {
            closeButton: true,
            id: WORKSPACE_NAVIGATION_ERROR_TOAST_ID,
          });
          return;
        }
        commitResumeDetailNavigation(
          intent,
          prepared,
          firstSavedImport.resume.id,
          resumes.length + 1,
          resumes.length + savedImports.length,
        );
        toast.success(messages.importResumeSuccess, { closeButton: true });
      } catch (error) {
        if (intent.isCurrent()) {
          intent.finish();
        }
        console.error("Failed to import resume.", error);
        if (!isApiErrorToastShown(error)) {
          toast.error(messages.importResumeFailed, { closeButton: true });
        }
      } finally {
        importInFlightRef.current = false;
        setIsImporting(false);
      }
    },
    [
      activeDefaultTemplateId,
      beginNavigation,
      commitResumeDetailNavigation,
      customTemplates,
      messages,
      persistence,
      resumes.length,
    ],
  );

  const moveResumesToTrash = useCallback(
    async (resumeIds: string[]) => {
      if (resumeIds.length === 0) {
        return;
      }

      const removing = resumes.filter((item) => resumeIds.includes(item.id));
      if (removing.length === 0) {
        return;
      }

      try {
        for (const resumeId of resumeIds) {
          await moveResumeToTrashApi(resumeId);
        }
      } catch (error) {
        console.error("Failed to move resume to trash.", error);
        if (!isApiErrorToastShown(error)) {
          toast.error(messages.loadError, { closeButton: true });
        }
        return;
      }

      setResumes((current) =>
        current.filter((item) => !resumeIds.includes(item.id)),
      );
      toast.success(
        resumeIds.length > 1 ? messages.resumesDeleted : messages.resumeDeleted,
        { closeButton: true },
      );
    },
    [messages, resumes],
  );

  return {
    changeTheme,
    createResume,
    hasLoaded,
    hasLoadError,
    importResume,
    isCreating,
    isImporting,
    moveResumesToTrash,
    openResume,
    resolvedTheme,
    resumes,
    routeData,
    retryLoad: () => setRetryKey((current) => current + 1),
    templateCatalog,
    theme,
  };
}
