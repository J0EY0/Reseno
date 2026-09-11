import { FileUp } from "lucide-react";
import { useRef, type ChangeEvent } from "react";

import { ConfirmActionDialog } from "@/components/confirm-action-dialog";
import { GalleryPagination } from "@/components/gallery-pagination";
import { GalleryToolbar } from "@/components/gallery-toolbar";
import { NewResumeDialog } from "@/components/new-resume-dialog";
import { useResumeThumbnailFonts } from "@/components/preview/resume-thumbnail-fonts";
import { ResumeGalleryGrid } from "@/components/resume-gallery-grid";
import { Button } from "@/components/ui/button";
import { Empty, EmptyDescription } from "@/components/ui/empty";
import { Spinner } from "@/components/ui/spinner";
import { useGalleryGridPageSize } from "@/components/use-gallery-grid-page-size";
import { useResumeGalleryController } from "@/components/use-resume-gallery-controller";
import type { AppMessages, Locale } from "@/i18n";
import type {
  DefaultTemplateIds,
  DocumentLocale,
  ResumeTemplateDefinition,
  ResumeTemplateId,
  ResumeWorkspaceItem,
} from "@/types/resume";

export function ResumeGallery({
  locale,
  t,
  resumes,
  templates,
  defaultTemplateIds,
  isImporting,
  importProgress,
  onRetryImport,
  onCancelImport,
  isCreating,
  openingResumeId,
  onPreloadResumeDetail,
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
  defaultTemplateIds: DefaultTemplateIds;
  isImporting: boolean;
  importProgress: { importedCount: number; remainingCount: number } | null;
  onRetryImport: () => void;
  onCancelImport: () => void;
  isCreating: boolean;
  openingResumeId: string | null;
  onPreloadResumeDetail: () => void;
  onOpenResume: (resumeId: string) => void;
  onCreateResume: (
    documentLocale: DocumentLocale,
    templateId: ResumeTemplateId,
  ) => void;
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
  useResumeThumbnailFonts(
    gallery.paginatedResumes.map((item) => item.typography.fontFamily),
  );

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
        disabled={isImporting || isCreating}
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
              disabled={isImporting || isCreating}
              onClick={() => fileInputRef.current?.click()}
            >
              {isImporting ? (
                <Spinner data-icon="inline-start" aria-label={t.importing} />
              ) : (
                <FileUp data-icon="inline-start" />
              )}
              {isImporting ? t.importing : t.importResume}
            </Button>
            {isImporting ? (
              <Button type="button" variant="outline" onClick={onCancelImport}>
                {t.resumeImportCancel}
              </Button>
            ) : null}
            <NewResumeDialog
              disabled={isImporting || isCreating}
              isCreating={isCreating}
              messages={t}
              templates={templates}
              defaultTemplateId={defaultTemplateIds[locale]}
              onCreateResume={onCreateResume}
            />
          </>
        }
      />
      {importProgress ? (
        <div
          className="mt-3 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-warning/40 bg-warning/5 p-3 text-sm"
          role="status"
          data-slot="resume-import-progress"
        >
          <p>
            {t.resumeImportPartial
              .replace("{count}", String(importProgress.importedCount))
              .replace("{failed}", String(importProgress.remainingCount))}
          </p>
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={onRetryImport}
          >
            {t.retry}
          </Button>
        </div>
      ) : null}
      {gallery.paginatedResumes.length === 0 ? (
        <Empty className="min-h-[390px]">
          <EmptyDescription className="font-medium">
            {resumes.length === 0 ? t.emptyResumes : t.emptyResumeSearch}
          </EmptyDescription>
        </Empty>
      ) : null}
      <div
        ref={gridRef}
        data-slot="gallery-grid"
        className="grid auto-rows-fr grid-cols-[repeat(auto-fill,minmax(208px,228px))] justify-center gap-4"
      >
        <ResumeGalleryGrid
          t={t}
          resumes={gallery.paginatedResumes}
          templates={templates}
          isSelecting={gallery.isSelecting}
          selectedIdSet={gallery.selectedIdSet}
          selectedCount={gallery.selectedResumeIds.length}
          openingResumeId={openingResumeId}
          updatedAtFormatter={gallery.updatedAtFormatter}
          onPreloadResumeDetail={onPreloadResumeDetail}
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
