import { useRef, useState } from "react";

import type {
  PendingTrashAction,
  RecycleBinPanelProps,
  TrashActionKey,
} from "@/components/recycle-bin-types";

type RecycleBinActionOptions = Pick<
  RecycleBinPanelProps,
  | "onRestoreResume"
  | "onDeleteResumeForever"
  | "onRestoreTemplate"
  | "onDeleteTemplateForever"
  | "deletedResumes"
  | "deletedTemplates"
>;

export function useRecycleBinActions({
  onRestoreResume,
  onDeleteResumeForever,
  onRestoreTemplate,
  onDeleteTemplateForever,
  deletedResumes,
  deletedTemplates,
}: RecycleBinActionOptions) {
  const [requestedAction, setRequestedAction] =
    useState<PendingTrashAction>(null);
  const remainingIds = requestedAction?.ids.filter((id) =>
    (requestedAction.type === "resume-item"
      ? deletedResumes
      : deletedTemplates
    ).some((item) => item.id === id),
  );
  const pendingAction =
    requestedAction && remainingIds?.length
      ? { ...requestedAction, ids: remainingIds }
      : null;
  const [runningActionKey, setRunningActionKey] =
    useState<TrashActionKey | null>(null);
  // Visible state drives feedback; the ref closes the same-render double-click gap.
  const runningActionRef = useRef<TrashActionKey | null>(null);

  function isRunning() {
    return runningActionRef.current !== null;
  }

  function closeDialog() {
    setRequestedAction(null);
  }

  function requestDelete(action: Exclude<PendingTrashAction, null>) {
    setRequestedAction(action);
  }

  async function runTrashAction(
    key: TrashActionKey,
    action: () => Promise<boolean>,
  ) {
    if (runningActionRef.current) {
      return false;
    }

    runningActionRef.current = key;
    setRunningActionKey(key);

    try {
      return await action();
    } finally {
      runningActionRef.current = null;
      setRunningActionKey(null);
    }
  }

  function restoreResumeIds(ids: string[], key: TrashActionKey) {
    return runTrashAction(key, () => onRestoreResume(ids));
  }

  function restoreTemplateIds(ids: string[], key: TrashActionKey) {
    return runTrashAction(key, () => onRestoreTemplate(ids));
  }

  async function confirmDelete() {
    const action = pendingAction;

    if (!action) {
      return null;
    }

    const succeeded =
      action.type === "resume-item"
        ? await runTrashAction("resume-delete", () =>
            onDeleteResumeForever(action.ids),
          )
        : await runTrashAction("template-delete", () =>
            onDeleteTemplateForever(action.ids),
          );

    if (!succeeded) {
      return null;
    }

    closeDialog();
    return action;
  }

  return {
    pendingAction,
    runningActionKey,
    isRunning,
    closeDialog,
    requestDelete,
    restoreResumeIds,
    restoreTemplateIds,
    confirmDelete,
  };
}
