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
import { isAbortError, isApiErrorToastShown } from "@/lib/api-client";
import { createTemplatePreviewResumes } from "@/lib/template-preview-resume";
import { getTemplateCatalog } from "@/lib/templates";
import {
  dismissWorkspaceLoadError,
  showWorkspaceLoadError,
} from "@/lib/workspace-load-error";
import { useWorkspaceLateralRouteData } from "@/components/workspace/use-workspace-lateral-route-data";
import { fetchWorkspacePageData } from "@/components/workspace/workspace-route-preparation";
import { useWorkspacePreferences } from "@/components/workspace/workspace-preferences-context";
import {
  deleteResumeForeverApi,
  deleteTemplateForeverApi,
  restoreResumeApi,
  restoreTemplateApi,
} from "@/lib/workspace-api";
import type {
  DefaultTemplateIds,
  DeletedResumeTemplateDefinition,
  DeletedResumeWorkspaceItem,
  ResumeTemplateDefinition,
} from "@/types/resume";

const initialDefaultTemplateIds: DefaultTemplateIds = {
  zh: "minimal",
  en: "minimal",
};

export function useTrashWorkspace({
  locale,
  messages,
}: {
  locale: Locale;
  messages: AppMessages;
}) {
  const preparedRouteData = useWorkspaceLateralRouteData("trash");
  const { persistence, theme } = useWorkspacePreferences();
  const initialLocaleRef = useRef(locale);
  const requestIdRef = useRef(0);
  const [retryKey, setRetryKey] = useState(0);
  const [hasLoaded, setHasLoaded] = useState(Boolean(preparedRouteData));
  const [hasLoadError, setHasLoadError] = useState(false);
  const [customTemplates, setCustomTemplates] = useState<
    ResumeTemplateDefinition[]
  >(() => preparedRouteData?.customTemplates ?? []);
  const [defaultTemplateIds, setDefaultTemplateIds] =
    useState<DefaultTemplateIds>(
      () => preparedRouteData?.defaultTemplateIds ?? initialDefaultTemplateIds,
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
      defaultTemplateIds,
      deletedResumes,
      deletedTemplates,
      theme,
    }),
    [
      customTemplates,
      defaultTemplateIds,
      deletedResumes,
      deletedTemplates,
      theme,
    ],
  );
  const templatePreviewResumes = useDeferredValue(
    useMemo(() => createTemplatePreviewResumes(messages), [messages]),
  );
  const loadRouteData = useCallback(
    async (signal: AbortSignal) => {
      const requestId = requestIdRef.current + 1;
      requestIdRef.current = requestId;
      setHasLoadError(false);
      dismissWorkspaceLoadError();

      try {
        const source = await fetchWorkspacePageData("trash", persistence, {
          notifyOnError: false,
          signal,
        });
        if (signal.aborted || requestIdRef.current !== requestId) {
          return;
        }

        setCustomTemplates(source.data.customTemplates);
        setDefaultTemplateIds(source.data.defaultTemplateIds);
        setDeletedResumes(source.data.deletedResumes);
        setDeletedTemplates(source.data.deletedTemplates);
        setHasLoaded(true);
      } catch (error) {
        if (
          signal.aborted ||
          isAbortError(error) ||
          requestIdRef.current !== requestId
        ) {
          return;
        }

        console.error("Failed to load the trash workspace route.", error);
        if (!isApiErrorToastShown(error)) {
          showWorkspaceLoadError(
            getMessagesSync(initialLocaleRef.current).apiMessages.REQUEST_FAILED,
          );
        }
        setHasLoaded(false);
        setHasLoadError(true);
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

  const restoreResumes = useCallback(
    async (resumeIds: string[]) => {
      const restoring = deletedResumes.filter((item) => resumeIds.includes(item.id));
      if (restoring.length === 0) {
        return false;
      }

      try {
        for (const item of restoring) {
          await restoreResumeApi(item.id);
          startTransition(() => {
            setDeletedResumes((current) =>
              current.filter((resume) => resume.id !== item.id),
            );
          });
        }
      } catch (error) {
        console.error("Failed to restore resume.", error);
        if (!isApiErrorToastShown(error)) {
          toast.error(messages.loadError, { closeButton: true });
        }
        return false;
      }

      toast.success(
        restoring.length > 1 ? messages.resumesRestored : messages.resumeRestored,
        { closeButton: true },
      );
      return true;
    },
    [deletedResumes, messages],
  );

  const permanentlyDeleteResumes = useCallback(
    async (resumeIds: string[]) => {
      const deleting = deletedResumes.filter((item) => resumeIds.includes(item.id));
      if (deleting.length === 0) {
        return false;
      }

      try {
        for (const item of deleting) {
          await deleteResumeForeverApi(item.id);
          startTransition(() => {
            setDeletedResumes((current) =>
              current.filter((resume) => resume.id !== item.id),
            );
          });
        }
      } catch (error) {
        console.error("Failed to permanently delete resume.", error);
        if (!isApiErrorToastShown(error)) {
          toast.error(messages.loadError, { closeButton: true });
        }
        return false;
      }

      toast.success(
        deleting.length > 1
          ? messages.resumesDeletedForever
          : messages.resumeDeletedForever,
        { closeButton: true },
      );
      return true;
    },
    [deletedResumes, messages],
  );

  const restoreTemplates = useCallback(
    async (templateIds: string[]) => {
      const restoring = deletedTemplates.filter((item) =>
        templateIds.includes(item.id),
      );
      if (restoring.length === 0) {
        return false;
      }

      try {
        for (const item of restoring) {
          const { template } = await restoreTemplateApi(item.id);
          startTransition(() => {
            setDeletedTemplates((current) =>
              current.filter((deleted) => deleted.id !== item.id),
            );
            setCustomTemplates((current) => [template, ...current]);
          });
        }
      } catch (error) {
        console.error("Failed to restore template.", error);
        if (!isApiErrorToastShown(error)) {
          toast.error(messages.loadError, { closeButton: true });
        }
        return false;
      }

      toast.success(
        restoring.length > 1
          ? messages.templatesRestored
          : messages.templateRestored,
        { closeButton: true },
      );
      return true;
    },
    [deletedTemplates, messages],
  );

  const permanentlyDeleteTemplates = useCallback(
    async (templateIds: string[]) => {
      const deleting = deletedTemplates.filter((item) => templateIds.includes(item.id));
      if (deleting.length === 0) {
        return false;
      }

      try {
        for (const item of deleting) {
          await deleteTemplateForeverApi(item.id);
          startTransition(() => {
            setDeletedTemplates((current) =>
              current.filter((template) => template.id !== item.id),
            );
          });
        }
      } catch (error) {
        console.error("Failed to permanently delete template.", error);
        if (!isApiErrorToastShown(error)) {
          toast.error(messages.loadError, { closeButton: true });
        }
        return false;
      }

      toast.success(
        deleting.length > 1
          ? messages.templatesDeletedForever
          : messages.templateDeletedForever,
        { closeButton: true },
      );
      return true;
    },
    [deletedTemplates, messages],
  );

  return {
    deletedResumes,
    deletedTemplates,
    hasLoaded,
    hasLoadError,
    permanentlyDeleteResumes,
    permanentlyDeleteTemplates,
    routeData,
    restoreResumes,
    restoreTemplates,
    retryLoad: () => setRetryKey((current) => current + 1),
    templatePreviewResumes,
    templates,
  };
}
