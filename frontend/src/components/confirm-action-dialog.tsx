import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Spinner } from "@/components/ui/spinner";

export function ConfirmActionDialog({
  open,
  title,
  description,
  confirmLabel,
  cancelLabel,
  onConfirm,
  onOpenChange,
  isPending = false,
  deferClose = false,
}: {
  open: boolean;
  title: string;
  description: string;
  confirmLabel: string;
  cancelLabel: string;
  onConfirm: () => void | Promise<void>;
  onOpenChange: (open: boolean) => void;
  isPending?: boolean;
  deferClose?: boolean;
}) {
  const resolvedTitle = title || confirmLabel;
  const resolvedDescription = description || "";

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent className="w-[min(440px,calc(100vw-2rem))]">
        <AlertDialogHeader>
          <AlertDialogTitle>{resolvedTitle}</AlertDialogTitle>
          {resolvedDescription ? (
            <AlertDialogDescription>
              {resolvedDescription}
            </AlertDialogDescription>
          ) : null}
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel type="button" disabled={isPending}>
            {cancelLabel}
          </AlertDialogCancel>
          <AlertDialogAction
            type="button"
            variant="destructive"
            disabled={isPending}
            onClick={(event) => {
              // Radix closes actions immediately by default. Async callers can
              // defer that close until their operation has actually succeeded.
              if (deferClose) {
                event.preventDefault();
              }

              void onConfirm();
            }}
          >
            {isPending ? (
              <Spinner data-icon="inline-start" aria-label={confirmLabel} />
            ) : null}
            {confirmLabel}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
