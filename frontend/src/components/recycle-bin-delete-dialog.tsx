import { ConfirmActionDialog } from "@/components/confirm-action-dialog";
import type { PendingTrashAction } from "@/components/recycle-bin-types";
import type { AppMessages } from "@/i18n";

export function RecycleBinDeleteDialog({
  t,
  pendingAction,
  isPending,
  isRunning,
  onConfirm,
  onClose,
}: {
  t: AppMessages;
  pendingAction: PendingTrashAction;
  isPending: boolean;
  isRunning: () => boolean;
  onConfirm: () => Promise<void>;
  onClose: () => void;
}) {
  const title =
    pendingAction?.type === "resume-item"
      ? pendingAction.ids.length > 1
        ? t.confirmDeleteResumesForeverTitle
        : t.confirmDeleteResumeForeverTitle
      : pendingAction?.type === "template-item"
        ? pendingAction.ids.length > 1
          ? t.confirmDeleteTemplatesForeverTitle
          : t.confirmDeleteTemplateForeverTitle
        : "";
  const description =
    pendingAction?.type === "resume-item"
      ? pendingAction.ids.length > 1
        ? t.confirmDeleteResumesForeverDescription
        : t.confirmDeleteResumeForeverDescription
      : pendingAction?.type === "template-item"
        ? pendingAction.ids.length > 1
          ? t.confirmDeleteTemplatesForeverDescription
          : t.confirmDeleteTemplateForeverDescription
        : "";
  const confirmLabel =
    (pendingAction?.ids.length ?? 0) > 1
      ? t.deleteSelectedForever
      : t.deleteForever;

  return (
    <ConfirmActionDialog
      open={Boolean(pendingAction)}
      title={title}
      description={description}
      confirmLabel={confirmLabel}
      cancelLabel={t.cancel}
      onConfirm={onConfirm}
      isPending={isPending}
      deferClose
      onOpenChange={(open) => {
        if (!open && !isRunning()) {
          onClose();
        }
      }}
    />
  );
}
