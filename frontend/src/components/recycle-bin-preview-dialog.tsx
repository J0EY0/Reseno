import { lazy, Suspense, useRef } from "react";

import { loadDocumentCanvas } from "@/components/preview/document-canvas-loader";
import type { RecycleBinPreviewTarget } from "@/components/recycle-bin-types";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import { WorkspacePreviewSkeleton } from "@/components/workspace-skeletons";
import type { AppMessages } from "@/i18n";
import { useLocalizedMessages } from "@/i18n/use-localized-messages";

const DocumentCanvas = lazy(loadDocumentCanvas);

export function RecycleBinPreviewDialog({
  t,
  target,
  open,
  onClose,
  restoreFocus,
}: {
  t: AppMessages;
  target: RecycleBinPreviewTarget | null;
  open: boolean;
  onClose: () => void;
  restoreFocus: () => void;
}) {
  const initialFocusRef = useRef<HTMLHeadingElement>(null);
  const documentLocale =
    target?.variant === "resume" ? target.documentLocale : null;
  const documentMessages = useLocalizedMessages(documentLocale);
  const previewMessages = target?.variant === "resume" ? documentMessages : t;
  const previewSkeleton = <WorkspacePreviewSkeleton />;

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen) {
          onClose();
        }
      }}
    >
      {target ? (
        <DialogContent
          closeLabel={t.close}
          className="h-[min(56rem,calc(100dvh-2rem))] grid-rows-[minmax(0,1fr)] gap-0 overflow-hidden rounded-(--radius-preview) border-0 bg-transparent p-0 shadow-none sm:max-w-5xl"
          onOpenAutoFocus={(event) => {
            event.preventDefault();
            initialFocusRef.current?.focus({ preventScroll: true });
          }}
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            restoreFocus();
          }}
        >
          <DialogTitle
            ref={initialFocusRef}
            className="sr-only"
            tabIndex={-1}
          >
            {t.preview}: {target.title}
          </DialogTitle>
          <DialogDescription className="sr-only">
            {t.recycleBinPreviewDescription}
          </DialogDescription>

          <div
            data-slot="trash-preview-dialog"
            className="min-h-0 overflow-hidden"
          >
            <Suspense fallback={previewSkeleton}>
              {!previewMessages ? (
                previewSkeleton
              ) : target.variant === "resume" ? (
                <DocumentCanvas
                  variant="resume"
                  t={t}
                  documentT={previewMessages}
                  resume={target.resume}
                  template={target.template}
                  typography={target.typography}
                />
              ) : (
                <DocumentCanvas
                  variant="template"
                  t={t}
                  documentT={previewMessages}
                  resume={target.resume}
                  template={target.template}
                />
              )}
            </Suspense>
          </div>
        </DialogContent>
      ) : null}
    </Dialog>
  );
}
