import { useRef, useState } from "react";

import type {
  PendingTrashAction,
  RecycleBinPanelProps,
  TrashActionKey,
} from "@/components/recycle-bin-types";

type TrashActionCallbacks = Pick<
  RecycleBinPanelProps,
  | "onRestoreResume"
  | "onDeleteResumeForever"
  | "onRestoreTemplate"
  | "onDeleteTemplateForever"
>;

export function useRecycleBinActions({
  onRestoreResume,
  onDeleteResumeForever,
  onRestoreTemplate,
  onDeleteTemplateForever,
}: TrashActionCallbacks) {
  const [pendingAction, setPendingAction] = useState<PendingTrashAction>(null);
  const [runningActionKey, setRunningActionKey] =
    useState<TrashActionKey | null>(null);
  // Visible state drives feedback; the ref closes the same-render double-click gap.
  const runningActionRef = useRef<TrashActionKey | null>(null);

  function isRunning() {
    return runningActionRef.current !== null;
  }

  function closeDialog() {
    setPendingAction(null);
  }

  function requestDelete(action: Exclude<PendingTrashAction, null>) {
    setPendingAction(action);
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
