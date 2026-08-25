import { FileUp, PlusSquare } from "lucide-react";
import { useRef, type ChangeEvent } from "react";

import { ConfirmActionDialog } from "@/components/confirm-action-dialog";
import { GalleryPagination } from "@/components/gallery-pagination";
import { GalleryToolbar } from "@/components/gallery-toolbar";
import { ResumeGalleryGrid } from "@/components/resume-gallery-grid";
import { Button } from "@/components/ui/button";
import { Empty, EmptyDescription } from "@/components/ui/empty";
import { Spinner } from "@/components/ui/spinner";
import { useGalleryGridPageSize } from "@/components/use-gallery-grid-page-size";
import { useResumeGalleryController } from "@/components/use-resume-gallery-controller";
import type { AppMessages, Locale } from "@/i18n";
import type {
  ResumeTemplateDefinition,
  ResumeWorkspaceItem,
} from "@/types/resume";

export function ResumeGallery({
  locale,
  t,
  resumes,
  templates,
  isImporting,
  isCreating,
  onOpenResume,
  onCreateResume,
  onImportResume,
  onDeleteResume,
  onBulkDeleteResumes,
}: {
  locale: Locale;
  t: AppMessages;
  resumes: ResumeWorkspaceItem[];
  templates: ResumeTemplateDefinition[];
  isImporting: boolean;
  isCreating: boolean;
  onOpenResume: (resumeId: string) => void;
  onCreateResume: () => void;
  onImportResume: (file: File) => void;
  onDeleteResume: (resumeId: string) => void;
  onBulkDeleteResumes: (resumeIds: string[]) => void;
}) {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const { gridRef, pageSize } = useGalleryGridPageSize({ fixedItems: 0 });
  const gallery = useResumeGalleryController({
    locale,
    resumes,
    pageSize,
    onDeleteResume,
    onBulkDeleteResumes,
  });

  function handleImportChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }
    onImportResume(file);
    event.target.value = "";
  }

  return (
    <section className="rounded-(--radius-workspace) border border-border bg-muted/35 p-3.5 text-foreground sm:p-4">
      <ConfirmActionDialog
        open={gallery.isDeleteDialogOpen}
        title={
          gallery.pendingDeleteIds.length > 1
            ? t.confirmDeleteResumesTitle
            : t.confirmDeleteResumeTitle
        }
        description={
          gallery.pendingDeleteIds.length > 1
            ? t.confirmDeleteResumesDescription
            : t.confirmDeleteResumeDescription
        }
        confirmLabel={t.confirmDeleteAction}
        cancelLabel={t.cancel}
        onConfirm={gallery.confirmDelete}
        onOpenChange={gallery.setDeleteDialogOpen}
      />
      <input
        ref={fileInputRef}
        type="file"
        accept=".pdf,application/pdf,.json,application/json"
        className="hidden"
        disabled={isImporting}
        onChange={handleImportChange}
      />
      <GalleryToolbar
        searchLabel={t.searchResumesLabel}
        searchName="resume-search"
        searchPlaceholder={t.searchResumesPlaceholder}
        searchValue={gallery.searchQuery}
        onSearchChange={gallery.setSearchQuery}
        isSelecting={gallery.isSelecting}
        onToggleSelecting={gallery.toggleSelecting}
        selectedCount={gallery.selectedResumeIds.length}
        selectLabel={t.selectItems}
        cancelLabel={t.cancelSelection}
        bulkDeleteLabel={t.bulkDelete}
        onBulkDelete={() => gallery.requestDelete(gallery.selectedResumeIds)}
        leadingActions={
          <>
            <Button
              type="button"
              variant="outline"
              disabled={isImporting}
              onClick={() => fileInputRef.current?.click()}
            >
              {isImporting ? (
                <Spinner data-icon="inline-start" aria-label={t.importing} />
              ) : (
                <FileUp data-icon="inline-start" />
              )}
              {isImporting ? t.importing : t.importResume}
            </Button>
            <Button
              type="button"
              disabled={isImporting || isCreating}
              onClick={onCreateResume}
            >
              {isCreating ? (
                <Spinner data-icon="inline-start" aria-label={t.newResume} />
              ) : (
                <PlusSquare data-icon="inline-start" />
              )}
              {t.newResume}
            </Button>
          </>
        }
      />
      {gallery.paginatedResumes.length === 0 ? (
        <Empty className="min-h-[390px]">
          <EmptyDescription className="font-medium">
            {resumes.length === 0 ? t.emptyResumes : t.emptyResumeSearch}
          </EmptyDescription>
        </Empty>
      ) : null}
      <div
        ref={gridRef}
        className="grid auto-rows-fr grid-cols-[repeat(auto-fit,minmax(208px,228px))] gap-4"
      >
        <ResumeGalleryGrid
          t={t}
          resumes={gallery.paginatedResumes}
          templates={templates}
          isSelecting={gallery.isSelecting}
          selectedIdSet={gallery.selectedIdSet}
          selectedCount={gallery.selectedResumeIds.length}
          updatedAtFormatter={gallery.updatedAtFormatter}
          onOpenResume={onOpenResume}
          onRequestDelete={gallery.requestDelete}
          onToggleSelected={gallery.toggleSelected}
        />
      </div>
      <GalleryPagination
        currentPage={gallery.safeCurrentPage}
        totalPages={gallery.totalPages}
        t={t}
        onPageChange={gallery.setCurrentPage}
      />
    </section>
  );
}
