import {
  startTransition,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";

import { useResumeDetailAgentLayout } from "@/components/workspace/use-resume-detail-agent-layout";
import { useResumeDetailCommands } from "@/components/workspace/use-resume-detail-commands";
import { useResumeDetailExport } from "@/components/workspace/use-resume-detail-export";
import { useResumeDetailLeave } from "@/components/workspace/use-resume-detail-leave";
import { useResumeDetailLoader } from "@/components/workspace/use-resume-detail-loader";
import { useResumeDetailPreferences } from "@/components/workspace/use-resume-detail-preferences";
import { useResumeDetailSave } from "@/components/workspace/use-resume-detail-save";
import { useResumeDetailSession } from "@/components/workspace/use-resume-detail-session";
import { usePreparedWorkspaceNavigation } from "@/components/workspace/use-prepared-workspace-navigation";
import { useWorkspaceNavigationTransaction } from "@/components/workspace/use-workspace-navigation-transaction";
import {
  prepareResumeDetailRoute,
  WORKSPACE_NAVIGATION_ERROR_TOAST_ID,
} from "@/components/workspace/workspace-route-preparation";
import type { ResumeDetailWorkspaceModel } from "@/components/workspace/resume-detail-workspace-types";
import type { AppMessages, Locale } from "@/i18n";
import type { AgentDraftDecisionResolution } from "@/lib/agent-session-run-client";
import { isAbortError } from "@/lib/api-client";
import { createTemplateSettings, getTemplateById, getTemplateCatalog } from "@/lib/templates";
import type { WorkspacePreferencesPersistence } from "@/lib/workspace-preferences-persistence";
import type { PreparedResumeDetailRouteData } from "@/lib/workspace-route-data";
import {
  createResumeDetailRouteHandoff,
  getResumeDetailRouteHandoff,
  getResumePath,
} from "@/lib/workspace-route";
import type { ResumeDetailResponse } from "@/types/api";
import type {
  ResumeData,
  ResumeTemplateDefinition,
  WorkspaceView,
} from "@/types/resume";

type ResolveAppliedDraft = (
  messageId: string,
  resume: ResumeData,
) => Promise<AgentDraftDecisionResolution>;

interface ResumeDetailWorkspaceOptions {
  locale: Locale;
  messages: AppMessages;
  onLocaleChange: (locale: Locale) => void;
  onLogout: () => void;
  persistence: WorkspacePreferencesPersistence;
  resumeId: string;
  routeState: unknown;
}

function areSettingsEqual(left: unknown, right: unknown) {
  return JSON.stringify(left) === JSON.stringify(right);
}

/** Composes the deep resume-detail modules into the pure render contract. */
export function useResumeDetailWorkspace({
  locale,
  messages,
  onLocaleChange,
  onLogout,
  persistence,
  resumeId,
  routeState,
}: ResumeDetailWorkspaceOptions) {
  const navigate = useNavigate();
  const { beginNavigation } = useWorkspaceNavigationTransaction();
  const initialDetail = useMemo(
    () => getResumeDetailRouteHandoff(routeState, resumeId),
    [resumeId, routeState],
  );
  const [isLoading, setIsLoading] = useState(!initialDetail);
  const [hasRouteLoadError, setHasRouteLoadError] = useState(false);
  const [customTemplates, setCustomTemplates] = useState<
    ResumeTemplateDefinition[]
  >(initialDetail?.payload.routeData.customTemplates ?? []);
  const resolveAppliedDraftRef = useRef<ResolveAppliedDraft | null>(null);
  const resolveAppliedDraft = useCallback<ResolveAppliedDraft>(
    (messageId, resume) => {
      const resolve = resolveAppliedDraftRef.current;
      if (!resolve) {
        throw new Error("Resume persistence is not ready.");
      }
      return resolve(messageId, resume);
    },
    [],
  );
  const session = useResumeDetailSession({
    initialResume: initialDetail?.payload.detail.resume ?? null,
    messages,
    onResolveAppliedDraft: resolveAppliedDraft,
  });
  const readIsLoading = useCallback(() => isLoading, [isLoading]);
  const preferences = useResumeDetailPreferences({
    initialRouteData: initialDetail?.payload.routeData,
    isLoading: readIsLoading,
    locale,
    messages,
    onLocaleChange,
    persistence,
  });
  const initialCheckpoint = useMemo(
    () =>
      initialDetail
        ? {
            savedAt: initialDetail.payload.detail.savedAt,
            versionId: initialDetail.payload.detail.versionId,
          }
        : undefined,
    [initialDetail],
  );
  const save = useResumeDetailSave({
    getSnapshot: session.getSnapshot,
    initialCheckpoint,
    initialResume: initialDetail?.payload.detail.resume ?? null,
    isLoading: isLoading || hasRouteLoadError,
    liveFingerprint: session.liveFingerprint,
    liveResume: session.liveResume,
    messages,
    onAdoptSavedResume: session.adoptSavedResume,
    onHydrateResume: session.hydrate,
    resumeId,
  });
  useLayoutEffect(() => {
    resolveAppliedDraftRef.current = save.resolveAppliedAgentDraft;
    return () => {
      resolveAppliedDraftRef.current = null;
    };
  }, [save.resolveAppliedAgentDraft]);

  const handleRouteLoad = useCallback(
    ({
      detail,
      routeData,
      versions,
    }: PreparedResumeDetailRouteData) => {
      const nextTemplateCatalog = getTemplateCatalog(
        messages,
        routeData.customTemplates,
      );
      const nextDefaultTemplateId =
        routeData.defaultTemplateIds[detail.resume.documentLocale];

      setCustomTemplates(routeData.customTemplates);
      preferences.hydrateRoutePreferences(routeData);
      if (
        !nextTemplateCatalog.some((item) => item.id === session.template)
      ) {
        session.setTemplate(nextDefaultTemplateId);
      }

      session.hydrate(detail.resume);
      save.hydratePersistedResume(detail, versions);
    },
    [messages, preferences, save, session],
  );
  const loader = useResumeDetailLoader({
    hasHandoff: Boolean(initialDetail),
    initialPreparedData: initialDetail?.payload ?? null,
    locale,
    onLoad: handleRouteLoad,
    onLoadErrorChange: setHasRouteLoadError,
    onLoadingChange: setIsLoading,
    persistence,
    resumeId,
  });
  const saveResume = save.save;

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (
        !(event.metaKey || event.ctrlKey) ||
        event.key.toLowerCase() !== "s"
      ) {
        return;
      }
      event.preventDefault();
      if (isLoading || loader.hasLoadError) {
        return;
      }
      void saveResume("checkpoint");
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isLoading, loader.hasLoadError, saveResume]);

  const templateCatalog = useMemo(
    () => getTemplateCatalog(messages, customTemplates),
    [customTemplates, messages],
  );

  const baseTemplate = getTemplateById(templateCatalog, session.template);
  const activeTemplate = useMemo<ResumeTemplateDefinition>(
    () => ({
      ...baseTemplate,
      settings: createTemplateSettings(baseTemplate.preset, {
        ...baseTemplate.settings,
        ...(session.templateSettings ?? {}),
      }),
    }),
    [baseTemplate, session.templateSettings],
  );
  const hasTemplateStyleOverrides =
    session.typography.fontFamily !== baseTemplate.typography.fontFamily ||
    session.typography.fontSize !== baseTemplate.typography.fontSize ||
    !areSettingsEqual(activeTemplate.settings, baseTemplate.settings);

  const leave = useResumeDetailLeave({
    discard: save.discard,
    hasUnsavedChanges: save.hasUnsavedChanges,
    markCheckpointPromotionSkipped: save.markCheckpointPromotionSkipped,
    messages,
    promoteCheckpoint: () =>
      save.save("checkpoint", { notifyOnError: false }),
    requiresCheckpointPromotion: save.requiresCheckpointPromotion,
    save: () => save.save(),
  });
  const { requestLeave } = leave;
  const {
    preload: preloadWorkspaceView,
    request: requestWorkspaceNavigation,
  } = usePreparedWorkspaceNavigation({
    persistence,
    preparationErrorMessage: messages.loadError,
    requestLeave,
    requiresLeaveResolution: () =>
      save.hasUnsavedChanges() || save.requiresCheckpointPromotion(),
  });

  const navigateToResume = useCallback(
    (detail: ResumeDetailResponse) => {
      const intent = beginNavigation();
      const nextResumeOrdinal = initialDetail
        ? initialDetail.resumeCount + 1
        : 1;

      const commitPreparedRoute = (
        prepared: PreparedResumeDetailRouteData,
      ) => {
        if (!intent.isCurrent()) {
          return;
        }

        startTransition(() => {
          if (!intent.isCurrent()) {
            return;
          }
          intent.finish();
          navigate(getResumePath(detail.resume.id), {
            state: createResumeDetailRouteHandoff(
              prepared,
              nextResumeOrdinal,
              nextResumeOrdinal,
            ),
          });
        });
      };

      const prepareFreshRoute = () => {
        if (!intent.isCurrent()) {
          return;
        }

        toast.dismiss(WORKSPACE_NAVIGATION_ERROR_TOAST_ID);
        void prepareResumeDetailRoute(
          detail.resume.id,
          persistence,
          { signal: intent.signal },
        )
          .then((prepared) => {
            if (!intent.isCurrent()) {
              return;
            }

            if (
              save.hasUnsavedChanges() ||
              save.requiresCheckpointPromotion()
            ) {
              requestLeave(prepareFreshRoute, intent.cancel);
              return;
            }

            commitPreparedRoute(prepared);
          })
          .catch((error) => {
            if (
              intent.signal.aborted ||
              isAbortError(error) ||
              !intent.isCurrent()
            ) {
              return;
            }
            intent.finish();
            console.error("Failed to prepare the duplicated resume route.", error);
            toast.error(messages.loadError, {
              closeButton: true,
              id: WORKSPACE_NAVIGATION_ERROR_TOAST_ID,
            });
          });
      };

      requestLeave(prepareFreshRoute, intent.cancel);
    },
    [
      beginNavigation,
      initialDetail,
      messages.loadError,
      navigate,
      persistence,
      requestLeave,
      save,
    ],
  );
  const documentCommands = useResumeDetailCommands({
    activeTemplate: baseTemplate,
    isLoading,
    messages,
    navigateToResume,
    resumeOrdinal: initialDetail?.resumeOrdinal ?? 1,
    save,
    session,
    templateCatalog,
  });
  const exporter = useResumeDetailExport({
    getSnapshot: session.getSnapshot,
    messages,
    save: () => save.save(),
    template: activeTemplate,
  });
  const agentLayout = useResumeDetailAgentLayout();

  const changeView = useCallback(
    (view: WorkspaceView) => {
      void requestWorkspaceNavigation(view);
    },
    [requestWorkspaceNavigation],
  );
  const back = useCallback(
    () => {
      void requestWorkspaceNavigation("resume");
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
  const openModelSettings = useCallback(
    () => {
      void requestWorkspaceNavigation("models");
    },
    [requestWorkspaceNavigation],
  );
  const changeSelectedModel = useCallback(
    (modelId: string) =>
      preferences.changeAgentSettings({
        ...preferences.agentSettings,
        defaultModelId: modelId,
      }),
    [preferences],
  );
  const selectVersion = useCallback(
    (versionId: string) =>
      requestLeave(() => {
        void save.selectVersion(versionId);
      }),
    [requestLeave, save],
  );

  const model: ResumeDetailWorkspaceModel = {
    commands: {
      agent: {
        applyDraft: session.applyAgentDraft,
        changeSelectedModel,
        discardDraft: session.discardAgentDraft,
        flushUserSettings: persistence.flush,
        openModelSettings,
        previewEdits: session.previewAgentEdits,
        reconcileDraft: session.reconcileAgentDraft,
        rollbackDraft: session.rollbackAgentDraft,
        setPanelCollapsed: agentLayout.setIsPanelCollapsed,
      },
      applyTemplate: documentCommands.applyTemplate,
      back,
      cancelLeave: leave.cancelLeave,
      changeTheme: preferences.changeTheme,
      changeTitleDraft: documentCommands.changeTitleDraft,
      changeView,
      discardAndLeave: leave.discardAndLeave,
      duplicateResume: documentCommands.duplicate,
      exportImages: exporter.exportImages,
      exportJson: exporter.exportJson,
      exportPdf: exporter.exportPdf,
      fitOnePage: documentCommands.fitOnePage,
      logout,
      onPreviewReadyChange: documentCommands.setPreviewReady,
      preloadView: preloadWorkspaceView,
      restoreTemplateDefaults: documentCommands.restoreTemplateDefaults,
      retryLoad: loader.retryLoad,
      save: () => save.save(),
      saveAndLeave: leave.saveAndLeave,
      saveTitle: documentCommands.saveTitle,
      selectVersion,
      setCollapsedState: session.setCollapsedState,
      setResume: session.setResume,
      setTitleDialogOpen: documentCommands.setTitleDialogOpen,
      updateTemplateSettings: documentCommands.updateTemplateSettings,
      updateTypography: session.setTypography,
    },
    state: {
      activeTemplate,
      agent: {
        draft: session.agentDraft,
        draftState: session.agentDraftState,
        isPanelCollapsed: agentLayout.isPanelCollapsed,
        modelConfigs: preferences.modelConfigs,
        selectedModelId: preferences.agentSettings.defaultModelId,
      },
      collapsedState: session.collapsedState,
      document: {
        isPreviewReady: documentCommands.isPreviewReady,
        isSmartFittingOnePage: documentCommands.isSmartFitting,
      },
      hasLoadError: loader.hasLoadError,
      hasVersionLoadError: save.hasVersionLoadError,
      hasTemplateStyleOverrides,
      isDuplicatingResume: documentCommands.isDuplicating,
      isExporting: exporter.isExporting,
      isLoading: isLoading || save.isVersionLoading,
      leave: {
        isOpen: leave.isOpen,
        isResolving: leave.isResolving,
      },
      previewResume: session.previewResume,
      resolvedTheme: preferences.resolvedTheme,
      resume: session.resume,
      resumeItem: session.resumeItem,
      save: {
        activeVersionId: save.activeVersionId,
        changeCount: save.changeCount,
        lastSavedAt: save.lastSavedAt,
        state: save.saveState,
        versions: save.versions,
      },
      showSkeleton: !loader.hasLoaded,
      template: session.template,
      templates: templateCatalog,
      theme: preferences.theme,
      title: {
        draft: documentCommands.titleDraft,
        isOpen: documentCommands.isTitleDialogOpen,
      },
      typography: session.typography,
    },
  };

  return { model, previewRef: documentCommands.documentPreviewRef };
}
