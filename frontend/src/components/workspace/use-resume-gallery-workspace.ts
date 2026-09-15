import {
  startTransition,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useNavigate } from "react-router-dom";
import {
  clearWorkspaceNavigationError,
  showWorkspaceNavigationError,
} from "@/components/workspace/workspace-navigation-notifications";
import { toast } from "sonner";

import { getMessagesSync, type AppMessages, type Locale } from "@/i18n";
import { isAbortError } from "@/lib/api-client";
import { notifyApiError } from "@/lib/api-error-notifier";
import { getTemplateCatalog } from "@/lib/templates";
import {
  dismissWorkspaceLoadError,
  showWorkspaceLoadError,
} from "@/lib/workspace-load-error";
import type {
  ResumeImportOptions,
  ResumeImportResult,
} from "@/components/workspace/resume-gallery-import";
import { getPdfImportErrorMessage } from "@/lib/pdf-resume-import/errors";
import { useWorkspaceLateralRouteData } from "@/components/workspace/use-workspace-lateral-route-data";
import { useWorkspacePreferences } from "@/components/workspace/workspace-preferences-context";
import {
  fetchWorkspacePageData,
  prepareCreatedResumeDetailRoute,
  prepareResumeDetailRoute,
  preloadResumeDetailRoute,
} from "@/components/workspace/workspace-route-preparation";
import {
  useWorkspaceNavigationTransaction,
  type WorkspaceNavigationIntent,
} from "@/components/workspace/use-workspace-navigation-transaction";
import { createResumeApi, moveResumeToTrashApi } from "@/lib/workspace-api";
import { getResumePath } from "@/lib/workspace-route";
import { createResumeDetailRouteHandoff } from "@/lib/workspace-detail-route-handoff";
import type {
  DefaultTemplateIds,
  DocumentLocale,
  ResumeTemplateDefinition,
  ResumeTemplateId,
  ResumeWorkspaceItem,
} from "@/types/resume";
import type { PreparedResumeDetailRouteData } from "@/lib/workspace-route-data";

const initialDefaultTemplateIds: DefaultTemplateIds = {
  zh: "minimal",
  en: "minimal",
};

export function useResumeGalleryWorkspace({
  locale,
  messages,
}: {
  locale: Locale;
  messages: AppMessages;
}) {
  const navigate = useNavigate();
  const preparedRouteData = useWorkspaceLateralRouteData("resume");
  const { persistence, theme } = useWorkspacePreferences();
  const initialLocaleRef = useRef(locale);
  const requestIdRef = useRef(0);
  const createInFlightRef = useRef(false);
  const activeImportRef = useRef<{
    intent: WorkspaceNavigationIntent;
    autoOpen: boolean;
  } | null>(null);
  const importOwnerActiveRef = useRef(true);
  const [pendingImport, setPendingImport] = useState<ResumeImportResult | null>(
    null,
  );

  useEffect(() => {
    importOwnerActiveRef.current = true;
    return () => {
      importOwnerActiveRef.current = false;
      activeImportRef.current?.intent.cancel();
    };
  }, []);
  const { beginNavigation } = useWorkspaceNavigationTransaction();
  const [retryKey, setRetryKey] = useState(0);
  const [hasLoaded, setHasLoaded] = useState(Boolean(preparedRouteData));
  const [hasLoadError, setHasLoadError] = useState(false);
  const [isLoading, setIsLoading] = useState(!preparedRouteData);
  const [isCreating, setIsCreating] = useState(false);
  const [isImporting, setIsImporting] = useState(false);
  const [openingResumeId, setOpeningResumeId] = useState<string | null>(null);
  const [resumes, setResumes] = useState<ResumeWorkspaceItem[]>(
    () => preparedRouteData?.resumes ?? [],
  );
  const [defaultTemplateIds, setDefaultTemplateIds] =
    useState<DefaultTemplateIds>(
      () => preparedRouteData?.defaultTemplateIds ?? initialDefaultTemplateIds,
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
      defaultTemplateIds,
      resumes,
      theme,
    }),
    [customTemplates, defaultTemplateIds, resumes, theme],
  );
  const loadRouteData = useCallback(
    async (signal: AbortSignal) => {
      const requestId = requestIdRef.current + 1;
      requestIdRef.current = requestId;
      setIsLoading(true);
      setHasLoadError(false);
      dismissWorkspaceLoadError();

      try {
        const source = await fetchWorkspacePageData(
          "resume-gallery",
          persistence,
          {
            notifyOnError: false,
            signal,
          },
        );
        if (signal.aborted || requestIdRef.current !== requestId) {
          return;
        }

        setResumes(source.data.resumes);
        setDefaultTemplateIds(source.data.defaultTemplateIds);
        setCustomTemplates(source.data.customTemplates);
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
        showWorkspaceLoadError(
          error,
          getMessagesSync(initialLocaleRef.current).apiMessages.REQUEST_FAILED,
        );
        setHasLoaded(false);
        setHasLoadError(true);
      } finally {
        if (!signal.aborted && requestIdRef.current === requestId) {
          setIsLoading(false);
        }
      }
    },
    [persistence],
  );

  useEffect(() => {
    if (preparedRouteData && retryKey === 0) {
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
  }, [loadRouteData, preparedRouteData, retryKey]);

  const buildResumeDetailHandoff = useCallback(
    (
      prepared: PreparedResumeDetailRouteData,
      resumeOrdinal: number,
      resumeCount: number,
    ) => createResumeDetailRouteHandoff(prepared, resumeOrdinal, resumeCount),
    [],
  );

  const preloadResumeDetail = useCallback(() => {
    void preloadResumeDetailRoute().catch((error) => {
      console.warn("Failed to warm the resume detail route.", error);
    });
  }, []);

  const clearOpeningResume = useCallback((resumeId: string) => {
    setOpeningResumeId((current) => (current === resumeId ? null : current));
  }, []);

  const commitResumeDetailNavigation = useCallback(
    (
      intent: WorkspaceNavigationIntent,
      prepared: PreparedResumeDetailRouteData,
      resumeId: string,
      resumeOrdinal: number,
      resumeCount: number,
      onCommit?: () => void,
    ) => {
      if (!intent.isCurrent()) {
        return;
      }

      startTransition(() => {
        if (!intent.isCurrent()) {
          return;
        }
        onCommit?.();
        setOpeningResumeId(null);
        intent.finish();
        navigate(getResumePath(resumeId), {
          state: buildResumeDetailHandoff(prepared, resumeOrdinal, resumeCount),
        });
      });
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

      setOpeningResumeId(resumeId);
      intent.signal.addEventListener(
        "abort",
        () => clearOpeningResume(resumeId),
        { once: true },
      );
      clearWorkspaceNavigationError();
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
          clearOpeningResume(resumeId);
          return;
        }
        clearOpeningResume(resumeId);
        intent.finish();
        console.error("Failed to prepare the resume detail route.", error);
        showWorkspaceNavigationError(messages.loadError);
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
      clearOpeningResume,
      commitResumeDetailNavigation,
      messages.loadError,
      persistence,
      resumes,
    ],
  );

  const createResume = useCallback(
    async (documentLocale: DocumentLocale, templateId: ResumeTemplateId) => {
      if (isLoading || createInFlightRef.current) {
        return;
      }

      const intent = beginNavigation();
      createInFlightRef.current = true;
      setIsCreating(true);
      preloadResumeDetail();

      try {
        const result = await createResumeApi({
          documentLocale,
          template: templateId,
        });
        const publishCreatedResume = () => {
          setResumes((current) =>
            current.some((item) => item.id === result.resume.id)
              ? current
              : [...current, result.resume],
          );
        };
        if (!intent.isCurrent()) {
          publishCreatedResume();
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
            publishCreatedResume();
            return;
          }
          publishCreatedResume();
          intent.finish();
          console.error("Failed to prepare the created resume route.", error);
          showWorkspaceNavigationError(messages.resumeCreatedOpenFailed);
          return;
        }
        commitResumeDetailNavigation(
          intent,
          prepared,
          result.resume.id,
          resumes.length + 1,
          resumes.length + 1,
          publishCreatedResume,
        );
      } catch (error) {
        if (intent.isCurrent()) {
          intent.finish();
        }
        console.error("Failed to create resume in backend.", error);
        notifyApiError(error, messages.loadError);
      } finally {
        createInFlightRef.current = false;
        setIsCreating(false);
      }
    },
    [
      beginNavigation,
      commitResumeDetailNavigation,
      isLoading,
      messages,
      persistence,
      preloadResumeDetail,
      resumes.length,
    ],
  );

  const runImport = useCallback(
    async (
      load: (options: ResumeImportOptions) => Promise<ResumeImportResult>,
    ) => {
      if (activeImportRef.current) return;

      const intent = beginNavigation();
      const operation = { intent, autoOpen: true };
      activeImportRef.current = operation;
      setIsImporting(true);
      setPendingImport(null);
      void preloadResumeDetailRoute().catch((error) => {
        console.warn("Failed to warm the resume detail route.", error);
      });

      try {
        const result = await load({
          signal: intent.signal,
          onResumeSaved: ({ resume }) => {
            if (importOwnerActiveRef.current) {
              setResumes((current) => [...current, resume]);
            }
          },
          onTemplateSaved: (template) => {
            if (importOwnerActiveRef.current) {
              setCustomTemplates((current) => [...current, template]);
            }
          },
        });
        if (!importOwnerActiveRef.current) return;
        if (result.remainingCount > 0) {
          setPendingImport(result);
          if (intent.isCurrent()) intent.finish();
          return;
        }
        toast.success(messages.importResumeSuccess, { closeButton: true });
        if (result.unclassifiedLineCount > 0) {
          toast.warning(
            messages.resumeImportUnclassified.replace(
              "{count}",
              String(result.unclassifiedLineCount),
            ),
            { closeButton: true, duration: 10000 },
          );
        }
        if (!intent.isCurrent() || !operation.autoOpen) {
          if (intent.isCurrent()) intent.finish();
          return;
        }
        const firstSavedImport = result.savedImports[0];
        if (!firstSavedImport) {
          intent.finish();
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
          )
            return;
          intent.finish();
          console.error("Failed to prepare the imported resume route.", error);
          showWorkspaceNavigationError(messages.loadError);
          return;
        }
        if (!operation.autoOpen) {
          if (intent.isCurrent()) intent.finish();
          return;
        }
        commitResumeDetailNavigation(
          intent,
          prepared,
          firstSavedImport.resume.id,
          resumes.length + 1,
          resumes.length + result.savedImports.length,
        );
      } catch (error) {
        if (intent.isCurrent()) intent.finish();
        if (intent.signal.aborted || isAbortError(error)) return;
        console.error("Failed to import resume.", error);
        notifyApiError(
          error,
          getPdfImportErrorMessage(error, messages) ??
            messages.importResumeFailed,
        );
      } finally {
        if (activeImportRef.current === operation)
          activeImportRef.current = null;
        if (importOwnerActiveRef.current) setIsImporting(false);
      }
    },
    [
      beginNavigation,
      commitResumeDetailNavigation,
      messages,
      persistence,
      resumes.length,
    ],
  );

  const importResume = useCallback(
    (file: File) =>
      runImport(async (options) => {
        const { importResumesIntoWorkspace } =
          await import("@/components/workspace/resume-gallery-import");
        return importResumesIntoWorkspace(file, options);
      }),
    [runImport],
  );
  const retryImport = useCallback(
    () => pendingImport?.retry && runImport(pendingImport.retry),
    [pendingImport, runImport],
  );
  const cancelImport = useCallback(
    () => activeImportRef.current?.intent.cancel(),
    [],
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
      if (activeImportRef.current) activeImportRef.current.autoOpen = false;

      try {
        for (const resumeId of resumeIds) {
          await moveResumeToTrashApi(resumeId);
        }
      } catch (error) {
        console.error("Failed to move resume to trash.", error);
        notifyApiError(error, messages.loadError);
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
    cancelImport,
    pendingImport,
    retryImport,
    createResume,
    hasLoaded,
    hasLoadError,
    importResume,
    isCreating,
    isImporting,
    moveResumesToTrash,
    openResume,
    openingResumeId,
    preloadResumeDetail,
    resumes,
    routeData,
    retryLoad: () => setRetryKey((current) => current + 1),
    templateCatalog,
  };
}
