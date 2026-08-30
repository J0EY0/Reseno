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
import {
  normalizeWorkspaceTheme,
  useWorkspaceTheme,
} from "@/components/workspace/workspace-theme-context";
import type { WorkspacePreferencesPersistence } from "@/lib/workspace-preferences-persistence";
import {
  deleteResumeForeverApi,
  deleteTemplateForeverApi,
  fetchWorkspaceRouteData,
  restoreResumeApi,
  restoreTemplateApi,
} from "@/lib/workspace-api";
import type {
  DeletedResumeTemplateDefinition,
  DeletedResumeWorkspaceItem,
  ResumeTemplateDefinition,
  ResumeTemplateId,
} from "@/types/resume";

export function useTrashWorkspace({
  locale,
  messages,
  persistence,
}: {
  locale: Locale;
  messages: AppMessages;
  persistence: WorkspacePreferencesPersistence;
}) {
  const preparedRouteData = useWorkspaceLateralRouteData("trash");
  const { hydrateTheme, theme } = useWorkspaceTheme();
  const initialLocaleRef = useRef(locale);
  const requestIdRef = useRef(0);
  const [retryKey, setRetryKey] = useState(0);
  const [hasLoaded, setHasLoaded] = useState(Boolean(preparedRouteData));
  const [hasLoadError, setHasLoadError] = useState(false);
  const [customTemplates, setCustomTemplates] = useState<
    ResumeTemplateDefinition[]
  >(() => preparedRouteData?.customTemplates ?? []);
  const [defaultTemplateId, setDefaultTemplateId] =
    useState<ResumeTemplateId>(
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
    [
      customTemplates,
      defaultTemplateId,
      deletedResumes,
      deletedTemplates,
      theme,
    ],
  );
  const templatePreviewResume = useDeferredValue(
    useMemo(() => createTemplatePreviewResume(messages), [messages]),
  );
  const loadRouteData = useCallback(
    async (signal: AbortSignal) => {
      const requestId = requestIdRef.current + 1;
      requestIdRef.current = requestId;
      setHasLoadError(false);
      toast.dismiss("workspace-load-error");

      try {
        await persistence.flush();
        if (signal.aborted || requestIdRef.current !== requestId) {
          return;
        }

        const source = await fetchWorkspaceRouteData("trash", {
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
        const persistedAgentSettings =
          persistedPreferences?.agentSettings ?? createDefaultAgentSettings();

        hydrateTheme(nextTheme);
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
          toast.error(
            getMessagesSync(initialLocaleRef.current).apiMessages.REQUEST_FAILED,
            { closeButton: true, id: "workspace-load-error" },
          );
        }
        setHasLoaded(false);
        setHasLoadError(true);
      }
    },
    [hydrateTheme, persistence],
  );

  useEffect(() => {
    if (preparedRouteData && retryKey === 0) {
      const persistedPreferences = persistence.getSnapshot();
      const nextTheme = preparedRouteData.theme
        ? normalizeWorkspaceTheme(preparedRouteData.theme)
        : persistedPreferences?.theme ?? "light";
      hydrateTheme(nextTheme);
      persistence.hydrate({
        locale: initialLocaleRef.current,
        theme: nextTheme,
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
  }, [hydrateTheme, loadRouteData, persistence, preparedRouteData, retryKey]);

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
    [deletedResumes, messages],
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
    [messages],
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
    [deletedTemplates, messages],
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
    [messages],
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
    templatePreviewResume,
    templates,
  };
}
