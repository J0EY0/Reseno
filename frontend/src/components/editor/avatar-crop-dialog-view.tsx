import type { AppMessages } from "@/i18n";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Spinner } from "@/components/ui/spinner";

import { AvatarCropCanvas } from "./avatar-crop-canvas";
import type { AvatarCropController } from "./use-avatar-crop";

export function AvatarCropDialogView({
  t,
  source,
  open,
  onCancel,
  controller,
}: {
  t: AppMessages;
  source: string;
  open: boolean;
  onCancel: () => void;
  controller: AvatarCropController;
}) {
  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen && !controller.isSaving) {
          onCancel();
        }
      }}
    >
      <DialogContent
        showCloseButton={!controller.isSaving}
        closeLabel={t.close}
        className="max-h-[calc(100dvh-2rem)] gap-0 overflow-y-auto p-0 sm:max-w-4xl"
        onEscapeKeyDown={(event) => {
          if (controller.isSaving) {
            event.preventDefault();
          }
        }}
        onPointerDownOutside={(event) => event.preventDefault()}
      >
        <DialogHeader className="border-b border-border px-6 py-5 text-left">
          <DialogTitle>{t.cropAvatar}</DialogTitle>
          <DialogDescription>{t.cropAvatarHint}</DialogDescription>
        </DialogHeader>

        <div className="grid gap-6 px-6 py-6 lg:grid-cols-[minmax(0,1fr)_240px]">
          <AvatarCropCanvas
            key={source}
            t={t}
            source={source}
            controller={controller}
          />
          <div className="grid content-start gap-5">
            <div className="grid gap-3">
              <p className="text-sm font-medium">{t.cropPreview}</p>
              <div className="flex items-center justify-center rounded-xl border border-border bg-muted/35 p-5">
                {controller.previewStyle ? (
                  <div
                    className="overflow-hidden border border-border bg-background"
                    style={controller.previewStyle}
                  />
                ) : (
                  <div className="flex h-[135px] w-[108px] items-center justify-center border border-dashed border-border bg-background px-3 text-center text-xs text-muted-foreground">
                    {t.cropPreview}
                  </div>
                )}
              </div>
            </div>
            <div className="rounded-xl border border-border bg-muted/35 p-4 text-sm leading-6 text-muted-foreground">
              {t.cropAvatarGuide}
            </div>
          </div>
        </div>

        <DialogFooter className="border-t border-border px-6 py-5">
          <Button
            type="button"
            variant="outline"
            onClick={onCancel}
            disabled={controller.isSaving}
          >
            {t.cancel}
          </Button>
          <Button
            type="button"
            onClick={() => void controller.confirmCrop()}
            disabled={controller.isSaving || !controller.hasCrop}
          >
            {controller.isSaving ? (
              <Spinner data-icon="inline-start" aria-label={t.saving} />
            ) : null}
            {controller.isSaving ? t.saving : t.applyCrop}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
