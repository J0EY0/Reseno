import {
  useCallback,
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
import { importResumePayload } from "@/lib/import-api";
import {
  createDefaultResumeTitle,
  normalizeResumeTitle,
} from "@/lib/resume-title";
import { getTemplateCatalog } from "@/lib/templates";
import { runViewTransition } from "@/lib/view-transition";
import type { WorkspacePreferencesPersistence } from "@/lib/workspace-preferences-persistence";
import {
  createResumeApi,
  createTemplateApi,
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
  ResumeTypographySettings,
  ResumeWorkspaceItem,
  ThemeMode,
} from "@/types/resume";
import type { ResumeDetailResponse } from "@/types/api";

const defaultTemplateId: ResumeTemplateId = "minimal";
const defaultTypography: ResumeTypographySettings = {
  fontFamily: "inter",
  fontSize: 16,
};

function preloadResumeDetailWorkspace() {
  return Promise.all([
    import("@/components/workspace/resume-detail-workspace-page"),
    import("@/components/preview/document-preview-card"),
  ]);
}

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
  const initialLocaleRef = useRef(locale);
  const requestIdRef = useRef(0);
  const createInFlightRef = useRef(false);
  const importInFlightRef = useRef(false);
  const [retryKey, setRetryKey] = useState(0);
  const [hasLoaded, setHasLoaded] = useState(false);
  const [hasLoadError, setHasLoadError] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [theme, setTheme] = useState<ThemeMode>(
    () => persistence.getSnapshot()?.theme ?? "light",
  );
  const [resolvedTheme, setResolvedTheme] = useState<"light" | "dark">(() =>
    document.documentElement.classList.contains("dark") ? "dark" : "light",
  );
  const [isCreating, setIsCreating] = useState(false);
  const [isImporting, setIsImporting] = useState(false);
  const [resumes, setResumes] = useState<ResumeWorkspaceItem[]>([]);
  const [activeDefaultTemplateId, setActiveDefaultTemplateId] =
    useState<ResumeTemplateId>(defaultTemplateId);
  const [customTemplates, setCustomTemplates] = useState<
    ResumeTemplateDefinition[]
  >([]);
  const templateCatalog = useMemo(
    () => getTemplateCatalog(messages, customTemplates),
    [customTemplates, messages],
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
        if (isAbortError(error)) {
          return;
        }
        if (requestIdRef.current !== requestId) {
          return;
        }

        console.error("Failed to load the resume gallery route.", error);
        if (!isApiErrorToastShown(error)) {
          toast.error(
            getMessagesSync(initialLocaleRef.current).apiMessages
              .REQUEST_FAILED,
            { closeButton: true, id: "workspace-load-error" },
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
    [persistence],
  );

  useEffect(() => {
    const controller = new AbortController();
    // Suppress StrictMode's development preflight before transport begins,
    // then abort a real in-flight read when this route releases ownership.
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
      resume: ResumeWorkspaceItem,
      resumeOrdinal: number,
      resumeCount: number,
      nextCustomTemplates: ResumeTemplateDefinition[] = customTemplates,
      checkpoint?: { savedAt: string; versionId: string },
    ) =>
      createResumeDetailRouteHandoff(
        resume,
        {
          customTemplates: nextCustomTemplates,
          defaultTemplateId: activeDefaultTemplateId,
          theme,
        },
        resumeOrdinal,
        resumeCount,
        checkpoint,
      ),
    [activeDefaultTemplateId, customTemplates, theme],
  );

  const openResume = useCallback(
    async (resumeId: string) => {
      const targetIndex = resumes.findIndex((item) => item.id === resumeId);
      const targetResume = resumes[targetIndex];
      if (!targetResume) {
        return;
      }

      try {
        // Resolve both cold detail seams before the transition captures them.
        await preloadResumeDetailWorkspace();
      } catch (error) {
        console.error("Failed to preload the resume detail route.", error);
        toast.error(messages.loadError, { closeButton: true });
        return;
      }

      runViewTransition(
        () =>
          navigate(getResumePath(resumeId), {
            state: buildResumeDetailHandoff(
              targetResume,
              targetIndex + 1,
              resumes.length,
            ),
          }),
        "nav-forward",
      );
    },
    [buildResumeDetailHandoff, messages.loadError, navigate, resumes],
  );

  const createResume = useCallback(async () => {
    if (isLoading || createInFlightRef.current) {
      return;
    }

    createInFlightRef.current = true;
    setIsCreating(true);
    void preloadResumeDetailWorkspace().catch((error) => {
      console.warn("Failed to warm the resume detail route.", error);
    });

    try {
      const result = await createResumeApi({
        title: createDefaultResumeTitle(messages, resumes.length + 1),
        template: activeDefaultTemplateId,
      });
      setResumes((current) => [...current, result.resume]);
      runViewTransition(
        () =>
          navigate(getResumePath(result.resume.id), {
            state: buildResumeDetailHandoff(
              result.resume,
              resumes.length + 1,
              resumes.length + 1,
              customTemplates,
              {
                savedAt: result.savedAt,
                versionId: result.versionId,
              },
            ),
          }),
        "nav-forward",
      );
    } catch (error) {
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
    buildResumeDetailHandoff,
    customTemplates,
    isLoading,
    messages,
    navigate,
    resumes.length,
  ]);

  const importResume = useCallback(
    async (file: File) => {
      if (importInFlightRef.current) {
        return;
      }

      importInFlightRef.current = true;
      setIsImporting(true);
      void preloadResumeDetailWorkspace().catch((error) => {
        console.warn("Failed to warm the resume detail route.", error);
      });

      try {
        const isPdfImport =
          file.type === "application/pdf" ||
          file.name.toLowerCase().endsWith(".pdf");
        const importedBundle = await (async () => {
          if (!isPdfImport) {
            return importResumePayload(file);
          }

          // The parser and PDF.js are loaded only after PDF intent is known.
          const { importResumeFromPdf } = await import(
            "@/lib/pdf-resume-import"
          );

          return {
            templates: [],
            resumes: [
              {
                title: normalizeResumeTitle(
                  file.name.replace(/\.pdf$/i, ""),
                  createDefaultResumeTitle(messages, resumes.length + 1),
                ),
                resume: await importResumeFromPdf(
                  file,
                  messages.importedResumeFallbackSection,
                ),
                jobBrief: "",
                typography: defaultTypography,
                template: activeDefaultTemplateId,
                templateSettings: null,
              },
            ],
          };
        })();
        if (importedBundle.resumes.length === 0) {
          throw new Error("No valid resume documents found in the imported file.");
        }

        const templateIdByArtifactRef = new Map<string, string>();
        const savedTemplates: ResumeTemplateDefinition[] = [];
        for (const embeddedTemplate of importedBundle.templates) {
          const result = await createTemplateApi(embeddedTemplate.definition);
          templateIdByArtifactRef.set(embeddedTemplate.ref, result.template.id);
          savedTemplates.push(result.template);
        }

        const savedImports: ResumeDetailResponse[] = [];
        for (const item of importedBundle.resumes) {
          const mappedTemplateId = templateIdByArtifactRef.get(item.template);
          if (item.template.startsWith("custom:") && !mappedTemplateId) {
            throw new Error("Imported resume references an unknown template.");
          }
          savedImports.push(
            await createResumeApi({
              title: item.title,
              resume: item.resume,
              jobBrief: item.jobBrief,
              typography: item.typography,
              template: mappedTemplateId ?? item.template,
              templateSettings: item.templateSettings ?? null,
            }),
          );
        }

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
        runViewTransition(
          () =>
            navigate(getResumePath(firstSavedImport.resume.id), {
              state: buildResumeDetailHandoff(
                firstSavedImport.resume,
                resumes.length + 1,
                resumes.length + savedImports.length,
                nextCustomTemplates,
                {
                  savedAt: firstSavedImport.savedAt,
                  versionId: firstSavedImport.versionId,
                },
              ),
            }),
          "nav-forward",
        );
        toast.success(messages.importResumeSuccess, { closeButton: true });
      } catch (error) {
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
      buildResumeDetailHandoff,
      customTemplates,
      messages,
      navigate,
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
    retryLoad: () => setRetryKey((current) => current + 1),
    templateCatalog,
    theme,
  };
}
