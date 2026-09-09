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
import { isAbortError } from "@/lib/api-client";
import { notifyApiError } from "@/lib/api-error-notifier";
import { importTemplatePayload } from "@/lib/import-api";
import { createTemplatePreviewResumes } from "@/lib/template-preview-resume";
import {
  dismissWorkspaceLoadError,
  showWorkspaceLoadError,
} from "@/lib/workspace-load-error";
import { useWorkspaceLateralRouteData } from "@/components/workspace/use-workspace-lateral-route-data";
import { useWorkspacePreferences } from "@/components/workspace/workspace-preferences-context";
import {
  fetchWorkspacePageData,
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
import type { PreparedTemplateDetailRouteData } from "@/lib/workspace-route-data";
import type { TemplateArtifactItem } from "@/types/api";
import {
  createTemplateApi,
  moveTemplateToTrashApi,
  saveDefaultTemplateApi,
} from "@/lib/workspace-api";
import { getTemplatePath } from "@/lib/workspace-route";
import { createTemplateDetailRouteHandoff } from "@/lib/workspace-detail-route-handoff";
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
}: {
  locale: Locale;
  messages: AppMessages;
}) {
  const navigate = useNavigate();
  const preparedRouteData = useWorkspaceLateralRouteData("templates");
  const { persistence, theme } = useWorkspacePreferences();
  const initialLocaleRef = useRef(locale);
  const requestIdRef = useRef(0);
  const createInFlightRef = useRef(false);
  const importInFlightRef = useRef(false);
  const importRetryRef = useRef({
    active: false,
    toasts: new Set<string | number>(),
  });
  const setDefaultInFlightRef = useRef(false);
  const { beginNavigation } = useWorkspaceNavigationTransaction();
  useEffect(() => {
    const retry = importRetryRef.current;
    retry.active = true;
    return () => {
      retry.active = false;
      retry.toasts.forEach((id) => toast.dismiss(id));
      retry.toasts.clear();
    };
  }, []);
  const [retryKey, setRetryKey] = useState(0);
  const [hasLoaded, setHasLoaded] = useState(Boolean(preparedRouteData));
  const [hasLoadError, setHasLoadError] = useState(false);
  const [isLoading, setIsLoading] = useState(!preparedRouteData);
  const [isCreating, setIsCreating] = useState(false);
  const [isImporting, setIsImporting] = useState(false);
  const [templateLocale, setTemplateLocale] = useState<DocumentLocale>(
    () => locale,
  );
  const [openingTemplateId, setOpeningTemplateId] = useState<string | null>(
    null,
  );
  const [settingDefaultTemplateId, setSettingDefaultTemplateId] = useState<
    string | null
  >(null);
  const [catalog, setCatalog] = useState(() => ({
    defaultTemplateIds:
      preparedRouteData?.defaultTemplateIds ?? initialDefaultTemplateIds,
    customTemplates: preparedRouteData?.customTemplates ?? [],
  }));
  const catalogRef = useRef(catalog);
  const deletingTemplateIdsRef = useRef(new Set<string>());
  const updateCatalog = useCallback(
    (update: (current: typeof catalog) => typeof catalog) => {
      const next = update(catalogRef.current);
      catalogRef.current = next;
      setCatalog(next);
      return next;
    },
    [],
  );
  const { customTemplates, defaultTemplateIds } = catalog;
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
        previewMessages ? createTemplatePreviewResumes(previewMessages) : null,
      [previewMessages],
    ),
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
          "template-gallery",
          persistence,
          {
            notifyOnError: false,
            signal,
          },
        );
        if (signal.aborted || requestIdRef.current !== requestId) {
          return;
        }

        updateCatalog(() => ({
          defaultTemplateIds: source.data.defaultTemplateIds,
          customTemplates: source.data.customTemplates,
        }));
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
    [persistence, updateCatalog],
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
      readData: () => PreparedTemplateDetailRouteData,
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
            readData(),
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
      let data: PreparedTemplateDetailRouteData;
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
        () => data,
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
      const publishCreatedTemplate = () => {
        updateCatalog((current) => ({
          ...current,
          customTemplates: [...current.customTemplates, result.template],
        }));
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
        () => ({
          checkpoint: null,
          ...catalogRef.current,
          theme,
        }),
        templateLocale,
        publishCreatedTemplate,
      );
      toast.success(messages.templateCreated, { closeButton: true });
    } catch (error) {
      if (intent.isCurrent()) {
        intent.finish();
      }
      console.error("Failed to create template in backend.", error);
      notifyApiError(error, messages.loadError);
    } finally {
      createInFlightRef.current = false;
      setIsCreating(false);
    }
  }, [
    beginNavigation,
    commitTemplateDetailNavigation,
    customTemplates,
    isLoading,
    messages,
    templateCatalog,
    templateLocale,
    theme,
    updateCatalog,
  ]);

  const importTemplateItems = useCallback(
    async function persistImports(load: () => Promise<TemplateArtifactItem[]>) {
      if (importInFlightRef.current || !importRetryRef.current.active) {
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
        const templates = await load();
        if (templates.length === 0) {
          throw new Error("No valid templates found in imported file.");
        }

        const savedImports: ResumeTemplateDefinition[] = [];
        const failedImports: TemplateArtifactItem[] = [];
        for (const item of templates) {
          try {
            const result = await createTemplateApi(item, {
              notifyOnError: false,
            });
            savedImports.push(result.template);
            updateCatalog((current) => ({
              ...current,
              customTemplates: [...current.customTemplates, result.template],
            }));
          } catch (error) {
            console.error("Failed to save imported template.", error);
            failedImports.push(item);
          }
        }
        if (failedImports.length > 0) {
          if (intent.isCurrent()) intent.finish();
          if (!importRetryRef.current.active) return;
          importRetryRef.current.toasts.add(
            toast.error(
              messages.templateImportPartial
                .replace("{count}", String(savedImports.length))
                .replace("{failed}", String(failedImports.length)),
              {
                closeButton: true,
                duration: Infinity,
                onDismiss: ({ id }) => importRetryRef.current.toasts.delete(id),
                action: {
                  label: messages.retry,
                  onClick: (event) => {
                    if (importInFlightRef.current)
                      return event.preventDefault();
                    void persistImports(async () => failedImports);
                  },
                },
              },
            ),
          );
          return;
        }

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
          console.error(
            "Failed to prepare the imported template route.",
            error,
          );
          toast.error(messages.loadError, {
            closeButton: true,
            id: WORKSPACE_NAVIGATION_ERROR_TOAST_ID,
          });
          return;
        }
        const firstImportedTemplate = savedImports.find((saved) =>
          catalogRef.current.customTemplates.some(
            (item) => item.id === saved.id,
          ),
        );
        if (!firstImportedTemplate) {
          intent.finish();
          return;
        }
        commitTemplateDetailNavigation(
          intent,
          firstImportedTemplate.id,
          () => ({ ...catalogRef.current, checkpoint: null, theme }),
          templateLocale,
        );
        toast.success(messages.templateImported, { closeButton: true });
      } catch (error) {
        if (intent.isCurrent()) {
          intent.finish();
        }
        console.error("Failed to import template JSON.", error);
        notifyApiError(error, messages.templateImportFailed);
      } finally {
        importInFlightRef.current = false;
        setIsImporting(false);
      }
    },
    [
      beginNavigation,
      commitTemplateDetailNavigation,
      messages,
      templateLocale,
      theme,
      updateCatalog,
    ],
  );
  const importTemplates = useCallback(
    (file: File) =>
      importTemplateItems(
        async () => (await importTemplatePayload(file)).templates,
      ),
    [importTemplateItems],
  );

  const deleteTemplates = useCallback(
    async (templateIds: string[]) => {
      const customTemplateIds = [...new Set(templateIds)].filter(
        (templateId) =>
          !deletingTemplateIdsRef.current.has(templateId) &&
          catalogRef.current.customTemplates.some(
            (item) => item.id === templateId,
          ),
      );
      if (customTemplateIds.length === 0) {
        return [];
      }
      customTemplateIds.forEach((id) => deletingTemplateIdsRef.current.add(id));
      const deletedIds: string[] = [];
      for (const templateId of customTemplateIds) {
        try {
          await moveTemplateToTrashApi(templateId, { notifyOnError: false });
          deletedIds.push(templateId);
          updateCatalog((current) => ({
            customTemplates: current.customTemplates.filter(
              (item) => item.id !== templateId,
            ),
            defaultTemplateIds: {
              zh:
                current.defaultTemplateIds.zh === templateId
                  ? baseTemplateId
                  : current.defaultTemplateIds.zh,
              en:
                current.defaultTemplateIds.en === templateId
                  ? baseTemplateId
                  : current.defaultTemplateIds.en,
            },
          }));
        } catch (error) {
          console.error("Failed to move template to trash.", error);
        } finally {
          deletingTemplateIdsRef.current.delete(templateId);
        }
      }
      if (deletedIds.length < customTemplateIds.length) {
        toast.error(
          messages.templateDeletePartial
            .replace("{count}", String(deletedIds.length))
            .replace(
              "{failed}",
              String(customTemplateIds.length - deletedIds.length),
            ),
          { closeButton: true },
        );
      } else {
        toast.success(
          customTemplateIds.length > 1
            ? messages.templatesDeleted
            : messages.templateDeleted,
          { closeButton: true },
        );
      }
      return deletedIds;
    },
    [messages, updateCatalog],
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
        const result = await saveDefaultTemplateApi(templateLocale, templateId);
        updateCatalog((current) => ({
          ...current,
          defaultTemplateIds: {
            ...current.defaultTemplateIds,
            [templateLocale]: getTemplateCatalog(
              messages,
              current.customTemplates,
            ).some(
              (item) => item.id === result.defaultTemplateIds[templateLocale],
            )
              ? result.defaultTemplateIds[templateLocale]
              : baseTemplateId,
          },
        }));
        toast.success(messages.defaultTemplateUpdated, { closeButton: true });
      } catch (error) {
        console.error("Failed to update default template.", error);
        notifyApiError(error, messages.loadError);
      } finally {
        setDefaultInFlightRef.current = false;
        setSettingDefaultTemplateId(null);
      }
    },
    [
      defaultTemplateIds,
      messages,
      templateCatalog,
      templateLocale,
      updateCatalog,
    ],
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
