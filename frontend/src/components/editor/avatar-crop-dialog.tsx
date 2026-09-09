import type { AppMessages } from "@/i18n";

import { AvatarCropDialogView } from "./avatar-crop-dialog-view";
import { useAvatarCrop } from "./use-avatar-crop";

export function AvatarCropDialog({
  t,
  source,
  open,
  onCancel,
  onConfirm,
}: {
  t: AppMessages;
  source: string | null;
  open: boolean;
  onCancel: () => void;
  onConfirm: (value: string) => void;
}) {
  const controller = useAvatarCrop({ source, open, onConfirm });

  if (!source) {
    return null;
  }

  return (
    <AvatarCropDialogView
      t={t}
      source={source}
      open={open}
      onCancel={onCancel}
      controller={controller}
    />
  );
}
