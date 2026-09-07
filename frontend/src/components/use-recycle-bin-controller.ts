import { useRef, useState } from "react";

import type {
  PendingTrashAction,
  RecycleBinPanelProps,
  RecycleBinPreviewTarget,
  TrashActionKey,
} from "@/components/recycle-bin-types";
import { useRecycleBinActions } from "@/components/use-recycle-bin-actions";
import { useRecycleBinSelection } from "@/components/use-recycle-bin-selection";

export function useRecycleBinController({
  deletedResumes,
  deletedTemplates,
  onRestoreResume,
  onDeleteResumeForever,
  onRestoreTemplate,
  onDeleteTemplateForever,
}: RecycleBinPanelProps) {
  const [previewTarget, setPreviewTarget] =
    useState<RecycleBinPreviewTarget | null>(null);
  const [isPreviewOpen, setIsPreviewOpen] = useState(false);
  const previewTriggerRef = useRef<string | null>(null);
  const actions = useRecycleBinActions({
    onRestoreResume,
    onDeleteResumeForever,
    onRestoreTemplate,
    onDeleteTemplateForever,
    deletedResumes,
    deletedTemplates,
  });
  const selection = useRecycleBinSelection({
    deletedResumes,
    deletedTemplates,
    isActionRunning: actions.isRunning,
  });

  async function restoreResumeIds(ids: string[], key: TrashActionKey) {
    if (await actions.restoreResumeIds(ids, key)) {
      selection.removeResumeIds(ids);
    }
  }

  async function restoreTemplateIds(ids: string[], key: TrashActionKey) {
    if (await actions.restoreTemplateIds(ids, key)) {
      selection.removeTemplateIds(ids);
    }
  }

  async function confirmAction() {
    const completedAction = await actions.confirmDelete();

    if (completedAction?.type === "resume-item") {
      selection.removeResumeIds(completedAction.ids);
    } else if (completedAction?.type === "template-item") {
      selection.removeTemplateIds(completedAction.ids);
    }
  }

  function requestDelete(action: Exclude<PendingTrashAction, null>) {
    actions.requestDelete(action);
  }

  function restoreSelectedResumes() {
    const ids = selection.selectedResumePageIds;
    if (ids.length > 0) {
      void restoreResumeIds([...ids], "resume-restore-selected");
    }
  }

  function restoreSelectedTemplates() {
    const ids = selection.selectedTemplatePageIds;
    if (ids.length > 0) {
      void restoreTemplateIds([...ids], "template-restore-selected");
    }
  }

  function deleteSelectedResumes() {
    const ids = selection.selectedResumePageIds;
    if (ids.length > 0) {
      requestDelete({ type: "resume-item", ids: [...ids] });
    }
  }

  function deleteSelectedTemplates() {
    const ids = selection.selectedTemplatePageIds;
    if (ids.length > 0) {
      requestDelete({ type: "template-item", ids: [...ids] });
    }
  }

  function openPreview(
    target: RecycleBinPreviewTarget,
    triggerId: string,
  ) {
    previewTriggerRef.current = triggerId;
    setPreviewTarget(target);
    setIsPreviewOpen(true);
  }

  function closePreview() {
    setIsPreviewOpen(false);
  }

  function restorePreviewFocus() {
    const triggerId = previewTriggerRef.current;
    previewTriggerRef.current = null;
    window.requestAnimationFrame(() => {
      if (!triggerId) {
        return;
      }
      document
        .querySelector<HTMLButtonElement>(
          `[data-trash-action-trigger="${CSS.escape(triggerId)}"]`,
        )
        ?.focus({ preventScroll: true });
    });
  }

  return {
    activeTab: selection.activeTab,
    changeTab: selection.changeTab,
    currentPage: selection.currentPage,
    changePage: selection.changePage,
    isBusy: actions.runningActionKey !== null,
    runningActionKey: actions.runningActionKey,
    dialog: {
      pendingAction: actions.pendingAction,
      isRunning: actions.isRunning,
      close: actions.closeDialog,
      confirm: confirmAction,
    },
    preview: {
      target: previewTarget,
      open: isPreviewOpen,
      show: openPreview,
      close: closePreview,
      restoreFocus: restorePreviewFocus,
    },
    resumes: {
      items: selection.paginatedDeletedResumes,
      totalPages: selection.resumeTotalPages,
      selectedPageIds: selection.selectedResumePageIds,
      setSelectedIds: selection.setSelectedResumeIds,
      restoreOne(id: string) {
        void restoreResumeIds([id], `resume-restore:${id}`);
      },
      restoreSelected: restoreSelectedResumes,
      deleteOne(id: string) {
        requestDelete({ type: "resume-item", ids: [id] });
      },
      deleteSelected: deleteSelectedResumes,
    },
    templates: {
      items: selection.paginatedDeletedTemplates,
      totalPages: selection.templateTotalPages,
      selectedPageIds: selection.selectedTemplatePageIds,
      setSelectedIds: selection.setSelectedTemplateIds,
      restoreOne(id: string) {
        void restoreTemplateIds([id], `template-restore:${id}`);
      },
      restoreSelected: restoreSelectedTemplates,
      deleteOne(id: string) {
        requestDelete({ type: "template-item", ids: [id] });
      },
      deleteSelected: deleteSelectedTemplates,
    },
  };
}

export type RecycleBinController = ReturnType<
  typeof useRecycleBinController
>;
