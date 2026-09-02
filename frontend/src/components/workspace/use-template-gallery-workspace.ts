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

import { getMessagesSync, type AppMessages, type Locale } from "@/i18n";
import { useLocalizedMessages } from "@/i18n/use-localized-messages";
import { createDefaultAgentSettings } from "@/lib/agent-settings";
import { isAbortError, isApiErrorToastShown } from "@/lib/api-client";
import { importTemplatePayload } from "@/lib/import-api";
import { createTemplatePreviewResumes } from "@/lib/template-preview-resume";
import { useWorkspaceLateralRouteData } from "@/components/workspace/use-workspace-lateral-route-data";
import {
  normalizeWorkspaceTheme,
  useWorkspaceTheme,
} from "@/components/workspace/workspace-theme-context";
import {
  prepareTemplateDetailRoute,
  preloadTemplateDetailRoute,
  WORKSPACE_NAVIGATION_ERROR_TOAST_ID,
} from "@/components/workspace/workspace-route-preparation";
import {
  useWorkspaceNavigationTransaction,
  type WorkspaceNavigationIntent,
} from "@/components/workspace/use-workspace-navigation-transaction";
import {
  createCustomTemplateFromBase,
  getTemplateById,
  getTemplateCatalog,
} from "@/lib/templates";
import type { WorkspacePreferencesPersistence } from "@/lib/workspace-preferences-persistence";
import type { WorkspaceTemplateRouteData } from "@/lib/workspace-route-data";
import {
  createTemplateApi,
  fetchWorkspaceRouteData,
  moveTemplateToTrashApi,
  saveDefaultTemplateApi,
} from "@/lib/workspace-api";
import {
  createTemplateDetailRouteHandoff,
  getTemplatePath,
} from "@/lib/workspace-route";
import type {
  DefaultTemplateIds,
  DocumentLocale,
  ResumeTemplateDefinition,
} from "@/types/resume";

const baseTemplateId = "minimal";
const initialDefaultTemplateIds: DefaultTemplateIds = {
  zh: baseTemplateId,
  en: baseTemplateId,
};

export function useTemplateGalleryWorkspace({
  locale,
  messages,
  persistence,
}: {
  locale: Locale;
  messages: AppMessages;
  persistence: WorkspacePreferencesPersistence;
}) {
  const navigate = useNavigate();
  const preparedRouteData = useWorkspaceLateralRouteData("templates");
  const { hydrateTheme, theme } = useWorkspaceTheme();
  const initialLocaleRef = useRef(locale);
  const requestIdRef = useRef(0);
  const createInFlightRef = useRef(false);
  const importInFlightRef = useRef(false);
  const setDefaultInFlightRef = useRef(false);
  const { beginNavigation } = useWorkspaceNavigationTransaction();
  const [retryKey, setRetryKey] = useState(0);
  const [hasLoaded, setHasLoaded] = useState(Boolean(preparedRouteData));
  const [hasLoadError, setHasLoadError] = useState(false);
  const [isLoading, setIsLoading] = useState(!preparedRouteData);
  const [isCreating, setIsCreating] = useState(false);
  const [isImporting, setIsImporting] = useState(false);
  const [templateLocale, setTemplateLocale] =
    useState<DocumentLocale>(() => locale);
  const [openingTemplateId, setOpeningTemplateId] = useState<string | null>(null);
  const [settingDefaultTemplateId, setSettingDefaultTemplateId] = useState<
    string | null
  >(null);
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
    () => ({ customTemplates, defaultTemplateIds, theme }),
    [customTemplates, defaultTemplateIds, theme],
  );
  const previewMessages = useLocalizedMessages(templateLocale);
  const previewResumes = useDeferredValue(
    useMemo(
      () =>
        previewMessages
          ? createTemplatePreviewResumes(previewMessages)
          : null,
      [previewMessages],
    ),
  );
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

        const source = await fetchWorkspaceRouteData("template-gallery", {
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
        setDefaultTemplateIds(source.data.defaultTemplateIds);
        setCustomTemplates(source.data.customTemplates);
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

        console.error("Failed to load the template gallery route.", error);
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

  const preloadTemplateDetail = useCallback(() => {
    void preloadTemplateDetailRoute().catch((error) => {
      console.warn("Failed to warm the template detail route.", error);
    });
  }, []);

  const clearOpeningTemplate = useCallback((templateId: string) => {
    setOpeningTemplateId((current) =>
      current === templateId ? null : current,
    );
  }, []);

  const commitTemplateDetailNavigation = useCallback(
    (
      intent: WorkspaceNavigationIntent,
      templateId: string,
      data: WorkspaceTemplateRouteData,
      targetLocale: DocumentLocale,
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
        setOpeningTemplateId(null);
        intent.finish();
        navigate(getTemplatePath(templateId), {
          state: createTemplateDetailRouteHandoff(
            templateId,
            data,
            targetLocale,
          ),
        });
      });
    },
    [navigate],
  );

  const openTemplate = useCallback(
    async (templateId: string) => {
      const intent = beginNavigation();
      if (!templateCatalog.some((item) => item.id === templateId)) {
        intent.finish();
        return;
      }

      setOpeningTemplateId(templateId);
      intent.signal.addEventListener(
        "abort",
        () => clearOpeningTemplate(templateId),
        { once: true },
      );
      toast.dismiss(WORKSPACE_NAVIGATION_ERROR_TOAST_ID);
      let data: WorkspaceTemplateRouteData;
      try {
        data = await prepareTemplateDetailRoute(templateId, persistence, {
          signal: intent.signal,
        });
      } catch (error) {
        if (
          intent.signal.aborted ||
          isAbortError(error) ||
          !intent.isCurrent()
        ) {
          clearOpeningTemplate(templateId);
          return;
        }
        clearOpeningTemplate(templateId);
        intent.finish();
        console.error("Failed to prepare the template detail route.", error);
        toast.error(messages.loadError, {
          closeButton: true,
          id: WORKSPACE_NAVIGATION_ERROR_TOAST_ID,
        });
        return;
      }

      commitTemplateDetailNavigation(
        intent,
        templateId,
        data,
        templateLocale,
      );
    },
    [
      beginNavigation,
      clearOpeningTemplate,
      commitTemplateDetailNavigation,
      messages.loadError,
      persistence,
      templateCatalog,
      templateLocale,
    ],
  );

  const createCustomTemplate = useCallback(async () => {
    if (isLoading || createInFlightRef.current) {
      return;
    }

    const intent = beginNavigation();
    createInFlightRef.current = true;
    setIsCreating(true);
    const detailRouteReady = preloadTemplateDetailRoute();
    void detailRouteReady.catch((error) => {
      console.warn("Failed to warm the template detail route.", error);
    });
    const sourceTemplate = getTemplateById(templateCatalog, baseTemplateId);
    const draftTemplate = createCustomTemplateFromBase(sourceTemplate, {
      name: `${messages.customTemplate} ${customTemplates.length + 1}`,
    });

    try {
      const result = await createTemplateApi(draftTemplate);
      const nextCustomTemplates = [...customTemplates, result.template];
      const publishCreatedTemplate = () => {
        setCustomTemplates((current) =>
          current.some((item) => item.id === result.template.id)
            ? current
            : [...current, result.template],
        );
      };
      if (!intent.isCurrent()) {
        publishCreatedTemplate();
        return;
      }
      try {
        await detailRouteReady;
      } catch (error) {
        if (!intent.isCurrent()) {
          publishCreatedTemplate();
          return;
        }
        publishCreatedTemplate();
        intent.finish();
        console.error("Failed to prepare the created template route.", error);
        toast.error(messages.templateCreatedOpenFailed, {
          closeButton: true,
          id: WORKSPACE_NAVIGATION_ERROR_TOAST_ID,
        });
        return;
      }
      commitTemplateDetailNavigation(
        intent,
        result.template.id,
        {
          customTemplates: nextCustomTemplates,
          defaultTemplateIds,
          theme,
        },
        templateLocale,
        publishCreatedTemplate,
      );
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
    commitTemplateDetailNavigation,
    customTemplates,
    defaultTemplateIds,
    isLoading,
    messages,
    templateCatalog,
    templateLocale,
    theme,
  ]);

  const importTemplates = useCallback(
    async (file: File) => {
      if (importInFlightRef.current) {
        return;
      }

      const intent = beginNavigation();
      importInFlightRef.current = true;
      setIsImporting(true);
      const detailRouteReady = preloadTemplateDetailRoute();
      void detailRouteReady.catch((error) => {
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
        setCustomTemplates(nextCustomTemplates);
        if (!intent.isCurrent()) {
          return;
        }
        try {
          await detailRouteReady;
        } catch (error) {
          if (!intent.isCurrent()) {
            return;
          }
          intent.finish();
          console.error("Failed to prepare the imported template route.", error);
          toast.error(messages.loadError, {
            closeButton: true,
            id: WORKSPACE_NAVIGATION_ERROR_TOAST_ID,
          });
          return;
        }
        commitTemplateDetailNavigation(
          intent,
          firstImportedTemplate.id,
          {
            customTemplates: nextCustomTemplates,
            defaultTemplateIds,
            theme,
          },
          templateLocale,
        );
        toast.success(messages.templateImported, { closeButton: true });
      } catch (error) {
        if (intent.isCurrent()) {
          intent.finish();
        }
        console.error("Failed to import template JSON.", error);
        if (!isApiErrorToastShown(error)) {
          toast.error(messages.templateImportFailed, { closeButton: true });
        }
      } finally {
        importInFlightRef.current = false;
        setIsImporting(false);
      }
    },
    [
      beginNavigation,
      commitTemplateDetailNavigation,
      customTemplates,
      defaultTemplateIds,
      messages,
      templateLocale,
      theme,
    ],
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

      setCustomTemplates((current) =>
        current.filter((item) => !customTemplateIds.includes(item.id)),
      );
      setDefaultTemplateIds((current) => ({
        zh: customTemplateIds.includes(current.zh) ? baseTemplateId : current.zh,
        en: customTemplateIds.includes(current.en) ? baseTemplateId : current.en,
      }));
      toast.success(
        customTemplateIds.length > 1
          ? messages.templatesDeleted
          : messages.templateDeleted,
        { closeButton: true },
      );
    },
    [customTemplates, messages],
  );

  const setDefaultTemplate = useCallback(
    async (templateId: string) => {
      const defaultTemplateId = defaultTemplateIds[templateLocale];
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
        const result = await saveDefaultTemplateApi(
          templateLocale,
          templateId,
        );
        setDefaultTemplateIds(result.defaultTemplateIds);
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
    [defaultTemplateIds, messages, templateCatalog, templateLocale],
  );

  return {
    createCustomTemplate,
    defaultTemplateId: defaultTemplateIds[templateLocale],
    deleteTemplates,
    hasLoaded,
    hasLoadError,
    importTemplates,
    isCreating,
    isImporting,
    openTemplate,
    openingTemplateId,
    preloadTemplateDetail,
    previewMessages,
    previewResumes,
    retryLoad: () => setRetryKey((current) => current + 1),
    routeData,
    setDefaultTemplate,
    settingDefaultTemplateId,
    setTemplateLocale,
    templateCatalog,
    templateLocale,
  };
}
