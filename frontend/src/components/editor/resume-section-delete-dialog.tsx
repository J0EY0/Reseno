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
import type { AppMessages } from "@/i18n";

export function ResumeSectionDeleteDialog({
  open,
  sectionId,
  t,
  onOpenChange,
  onCloseAutoFocus,
  onRemoveSection,
}: {
  open: boolean;
  sectionId: string;
  t: AppMessages;
  onOpenChange: (open: boolean) => void;
  onCloseAutoFocus: (event: Event) => void;
  onRemoveSection: (sectionId: string) => void;
}) {
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent size="sm" onCloseAutoFocus={onCloseAutoFocus}>
        <AlertDialogHeader>
          <AlertDialogTitle>{t.confirmDeleteSectionTitle}</AlertDialogTitle>
          <AlertDialogDescription>
            {t.confirmDeleteSectionDescription}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>{t.cancel}</AlertDialogCancel>
          <AlertDialogAction
            variant="destructive"
            onClick={() => onRemoveSection(sectionId)}
          >
            {t.deleteSection}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
