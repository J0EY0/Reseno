import {
  startTransition,
  useCallback,
  useDeferredValue,
  useEffect,
  useMemo,
  useState,
} from "react";
import { useNavigate } from "react-router-dom";
import {
  clearWorkspaceNavigationError,
  showWorkspaceNavigationError,
} from "@/components/workspace/workspace-navigation-notifications";

import { useResumeDetailAgentLayout } from "@/components/workspace/use-resume-detail-agent-layout";
import { useResumeDetailCommands } from "@/components/workspace/use-resume-detail-commands";
import { useResumeDetailExport } from "@/components/workspace/use-resume-detail-export";
import { useResumeDetailLeave } from "@/components/workspace/use-resume-detail-leave";
import { useResumeDetailLoader } from "@/components/workspace/use-resume-detail-loader";
import { useResumeDetailModels } from "@/components/workspace/use-resume-detail-models";
import { useWorkspacePreferences } from "@/components/workspace/workspace-preferences-context";
import { useResumeDetailSave } from "@/components/workspace/use-resume-detail-save";
import { useResumeDetailSession } from "@/components/workspace/use-resume-detail-session";
import { useWorkspaceResourceRecovery } from "@/components/workspace/use-workspace-resource-recovery";
import { usePreparedWorkspaceNavigation } from "@/components/workspace/use-prepared-workspace-navigation";
import { useWorkspaceNavigationTransaction } from "@/components/workspace/use-workspace-navigation-transaction";
import { prepareResumeDetailRoute } from "@/components/workspace/workspace-route-preparation";
import type { ResumeDetailWorkspaceModel } from "@/components/workspace/resume-detail-workspace-types";
import type { AppMessages, Locale } from "@/i18n";
import { useResumeAgentDraft } from "@/hooks/use-resume-agent-draft";
import { isAbortError } from "@/lib/api-client";
import { notifyApiError } from "@/lib/api-error-notifier";
import {
  createTemplateSettings,
  getTemplateById,
  getTemplateCatalog,
} from "@/lib/templates";
import type { PreparedResumeDetailRouteData } from "@/lib/workspace-route-data";
import { getResumePath } from "@/lib/workspace-route";
import {
  createResumeDetailRouteHandoff,
  getResumeDetailRouteHandoff,
} from "@/lib/workspace-detail-route-handoff";
import type { ResumeDetailResponse } from "@/types/api";
import type {
  ResumeWorkspaceItem,
  ResumeTemplateDefinition,
  WorkspaceView,
} from "@/types/resume";

interface ResumeDetailWorkspaceOptions {
  locale: Locale;
  messages: AppMessages;
  onLogout: () => void;
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
  onLogout,
  resumeId,
  routeState,
}: ResumeDetailWorkspaceOptions) {
  const navigate = useNavigate();
  const preferences = useWorkspacePreferences();
  const { persistence } = preferences;
  const { beginNavigation } = useWorkspaceNavigationTransaction();
  const initialDetail = useMemo(
    () => getResumeDetailRouteHandoff(routeState, resumeId),
    [resumeId, routeState],
  );
  const [customTemplates, setCustomTemplates] = useState<
    ResumeTemplateDefinition[]
  >(initialDetail?.payload.routeData.customTemplates ?? []);
  const session = useResumeDetailSession({
    initialResume: initialDetail?.payload.detail.resume ?? null,
  });
  const models = useResumeDetailModels({
    initialRouteData: initialDetail?.payload.routeData,
    locale,
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
  const loader = useResumeDetailLoader({
    initialPreparedData: initialDetail?.payload ?? null,
    locale,
    onLoad: handleRouteLoad,
    persistence,
    resumeId,
  });
  const { isLoading } = loader;
  const agent = useResumeAgentDraft({
    messages,
    onApplyResume: session.applyAgentResume,
    onResolveDraftReview: resolveAgentDraftReview,
    resume: session.resume,
    resumeId: session.document?.id,
  });
  const save = useResumeDetailSave({
    autosavePaused: Boolean(agent.review?.resolvingStatus),
    getFingerprint: session.getFingerprint,
    getSnapshot: session.getSnapshot,
    initialCheckpoint,
    initialResume: initialDetail?.payload.detail.resume ?? null,
    isLoading: isLoading || loader.hasLoadError,
    liveFingerprint: session.fingerprint,
    liveResume: session.document,
    messages,
    onAdoptSavedResume: session.adoptSavedResume,
    onHydrateResume: hydrateResume,
    resumeId,
  });
  const editingDisabled =
    isLoading ||
    loader.hasLoadError ||
    save.isViewingHistory ||
    save.isVersionLoading ||
    save.isRestoringVersion ||
    Boolean(agent.review?.resolvingStatus);
  const { undo: undoDocument, redo: redoDocument } = session;
  const undo = useCallback(() => {
    if (!editingDisabled) undoDocument();
  }, [editingDisabled, undoDocument]);
  const redo = useCallback(() => {
    if (!editingDisabled) redoDocument();
  }, [editingDisabled, redoDocument]);
  const previewPresentation = useMemo(() => {
    if (agent.review) {
      return { ...agent.review.projection, review: agent.review };
    }
    return {
      diffs: agent.agentDraft?.diffs,
      review: null,
      resume: agent.agentDraft?.resume ?? session.resume,
    };
  }, [
    agent.review,
    agent.agentDraft?.diffs,
    agent.agentDraft?.resume,
    session.resume,
  ]);
  const deferredPreviewPresentation = useDeferredValue(previewPresentation);
  const preview =
    previewPresentation.review || deferredPreviewPresentation.review
      ? previewPresentation
      : deferredPreviewPresentation;

  function hydrateResume(item: ResumeWorkspaceItem) {
    agent.resetAgentDraft();
    session.hydrate(item);
  }

  function resolveAgentDraftReview(
    ...args: Parameters<
      ReturnType<typeof useResumeDetailSave>["resolveAgentDraftReview"]
    >
  ) {
    return save.resolveAgentDraftReview(...args);
  }

  function handleRouteLoad({
    detail,
    routeData,
    versions,
  }: PreparedResumeDetailRouteData) {
    setCustomTemplates(routeData.customTemplates);
    models.hydrateModels(routeData);
    hydrateResume(detail.resume);
    save.hydratePersistedResume(detail, versions);
  }
  const saveResume = save.save;
  const saveAndReload = useWorkspaceResourceRecovery({
    saveCheckpoint: () => saveResume("checkpoint", { notifyOnError: false }),
    hasUnsavedChanges: save.hasUnsavedChanges,
    beginNavigation,
  });
  const saveCheckpoint = useCallback(() => {
    if (editingDisabled) return;
    void saveResume("checkpoint").catch(notifyApiError);
  }, [editingDisabled, saveResume]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (
        !(event.metaKey || event.ctrlKey) ||
        event.key.toLowerCase() !== "s"
      ) {
        return;
      }
      event.preventDefault();
      if (editingDisabled) {
        return;
      }
      saveCheckpoint();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [editingDisabled, saveCheckpoint]);

  useEffect(() => {
    const handleHistoryKey = (event: KeyboardEvent) => {
      if (
        event.defaultPrevented ||
        event.isComposing ||
        event.altKey ||
        !(event.metaKey || event.ctrlKey)
      )
        return;
      const target = event.target;
      if (
        target instanceof Element &&
        target.closest(
          'input, textarea, select, [contenteditable="true"], [role="dialog"], [role="alertdialog"], #resume-detail-agent-panel',
        )
      )
        return;
      const key = event.key.toLowerCase();
      if (key !== "z" && !(key === "y" && event.ctrlKey && !event.metaKey))
        return;
      event.preventDefault();
      if (key === "y" || event.shiftKey) redo();
      else undo();
    };
    window.addEventListener("keydown", handleHistoryKey);
    return () => window.removeEventListener("keydown", handleHistoryKey);
  }, [undo, redo]);

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
  const historyTemplate = save.historyVersion
    ? getTemplateById(templateCatalog, save.historyVersion.resume.template)
    : null;
  const historyPreviewTemplate =
    historyTemplate && save.historyVersion
      ? {
          ...historyTemplate,
          settings: createTemplateSettings(historyTemplate.preset, {
            ...historyTemplate.settings,
            ...(save.historyVersion.resume.templateSettings ?? {}),
          }),
        }
      : null;

  const leave = useResumeDetailLeave({
    discard: save.discard,
    hasUnsavedChanges: save.hasUnsavedChanges,
    isCommitting:
      save.isRestoringVersion || Boolean(agent.review?.resolvingStatus),
    markCheckpointPromotionSkipped: save.markCheckpointPromotionSkipped,
    messages,
    promoteCheckpoint: () => save.save("checkpoint", { notifyOnError: false }),
    requiresCheckpointPromotion: save.requiresCheckpointPromotion,
    save: () => save.save(),
  });
  const { requestLeave } = leave;
  const { preload: preloadWorkspaceView, request: requestWorkspaceNavigation } =
    usePreparedWorkspaceNavigation({
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

      const commitPreparedRoute = (prepared: PreparedResumeDetailRouteData) => {
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

        clearWorkspaceNavigationError();
        void prepareResumeDetailRoute(detail.resume.id, persistence, {
          signal: intent.signal,
        })
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
            console.error(
              "Failed to prepare the duplicated resume route.",
              error,
            );
            showWorkspaceNavigationError(messages.loadError);
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
    disabled: editingDisabled,
    messages,
    navigateToResume,
    previewResume: preview.resume,
    resumeOrdinal: initialDetail?.resumeOrdinal ?? 1,
    save,
    session,
    templateCatalog,
  });
  const exporter = useResumeDetailExport({
    messages,
    save: () => save.save(),
    templates: templateCatalog,
  });
  const previewTemplate = useMemo(
    () =>
      documentCommands.previewStyle
        ? {
            ...activeTemplate,
            settings: createTemplateSettings(activeTemplate.preset, {
              ...activeTemplate.settings,
              ...documentCommands.previewStyle.templateSettings,
            }),
          }
        : activeTemplate,
    [activeTemplate, documentCommands.previewStyle],
  );
  const agentLayout = useResumeDetailAgentLayout(session.document?.id);

  const changeView = useCallback(
    (view: WorkspaceView) => {
      void requestWorkspaceNavigation(view);
    },
    [requestWorkspaceNavigation],
  );
  const back = useCallback(() => {
    void requestWorkspaceNavigation("resume");
  }, [requestWorkspaceNavigation]);
  const logout = useCallback(() => {
    const intent = beginNavigation();
    requestLeave(() => {
      if (!intent.isCurrent()) {
        return;
      }
      intent.finish();
      onLogout();
    }, intent.cancel);
  }, [beginNavigation, onLogout, requestLeave]);
  const openModelSettings = useCallback(() => {
    void requestWorkspaceNavigation("models");
  }, [requestWorkspaceNavigation]);
  const changeSelectedModelConfig = useCallback(
    (modelConfigId: string) => {
      if (!preferences.agentSettings) {
        return;
      }
      preferences.changeAgentSettings({
        ...preferences.agentSettings,
        defaultModelConfigId: modelConfigId,
      });
    },
    [preferences],
  );
  const selectVersion = useCallback(
    (versionId: string) => {
      if (isLoading || agent.review?.resolvingStatus || save.isRestoringVersion)
        return;
      requestLeave(() => {
        void save.selectVersion(versionId);
      });
    },
    [agent.review?.resolvingStatus, isLoading, requestLeave, save],
  );

  const model: ResumeDetailWorkspaceModel = {
    commands: {
      undo,
      redo,
      finishHistoryGroup: session.finishHistoryGroup,
      activateSection: session.activateSection,
      restoreVersion: save.restoreVersion,
      returnToLatest: save.returnToLatest,
      agent: {
        applyDraft: agent.applyAgentDraft,
        changeSelectedModelConfig,
        discardDraft: agent.discardAgentDraft,
        flushUserSettings: persistence.flush,
        openModelSettings,
        previewEdits: agent.previewAgentEdits,
        reconcileDraft: agent.reconcileAgentDraft,
        reportPanelStatus: agentLayout.reportPanelStatus,
        rollbackDraft: agent.rollbackAgentDraft,
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
      save: saveCheckpoint,
      saveAndReload,
      saveAndLeave: leave.saveAndLeave,
      saveTitle: documentCommands.saveTitle,
      selectVersion,
      addSection: session.addSection,
      removeSection: session.removeSection,
      toggleSection: session.toggleSection,
      updateContent: session.updateContent,
      setTitleDialogOpen: documentCommands.setTitleDialogOpen,
      updateTemplateSettings: documentCommands.updateTemplateSettings,
      updateTypography: (typography) => session.updateStyle({ typography }),
    },
    state: {
      history: {
        version: save.historyVersion,
        isRestoring: save.isRestoringVersion,
        hasRestoreError: save.hasVersionRestoreError,
      },
      editing: {
        canUndo: session.canUndo,
        canRedo: session.canRedo,
        disabled: editingDisabled,
      },
      sectionNavigation: session.sectionNavigation,
      activeTemplate,
      previewTemplate: historyPreviewTemplate ?? previewTemplate,
      previewTypography:
        save.historyVersion?.resume.typography ??
        documentCommands.previewStyle?.typography ??
        session.typography,
      agent: {
        draft: agent.agentDraft,
        draftState: agent.agentDraftState,
        isPanelCollapsed: save.isViewingHistory || agentLayout.isPanelCollapsed,
        modelConfigs: models.modelConfigs,
        panelStatus: agentLayout.panelStatus,
        review: agent.review,
        selectedModelConfigId:
          preferences.agentSettings?.defaultModelConfigId ?? "",
      },
      openSectionId: session.openSectionId,
      document: {
        isPreviewReady: documentCommands.isPreviewReady,
        isSmartFittingOnePage: documentCommands.isSmartFitting,
        measurementKey: documentCommands.previewStyle ?? undefined,
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
      previewResume: save.historyVersion?.resume.resume ?? preview.resume,
      previewDiffs: save.isViewingHistory ? undefined : preview.diffs,
      previewReview: save.isViewingHistory ? null : preview.review,
      resolvedTheme: preferences.resolvedTheme,
      resume: session.resume,
      resumeItem: session.document,
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
