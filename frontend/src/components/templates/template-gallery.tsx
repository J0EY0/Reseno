import { CopyPlus, FileUp } from "lucide-react";
import { useRef, type ChangeEvent } from "react";

import { ConfirmActionDialog } from "@/components/confirm-action-dialog";
import { GalleryPagination } from "@/components/gallery-pagination";
import { GalleryToolbar } from "@/components/gallery-toolbar";
import { useGalleryGridPageSize } from "@/components/use-gallery-grid-page-size";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import type { AppMessages } from "@/i18n";
import type {
  ResumeData,
  ResumeTemplateDefinition,
} from "@/types/resume";

import { TemplateGalleryGrid } from "./template-gallery-grid";
import { useTemplateGalleryController } from "./use-template-gallery-controller";

interface TemplateGalleryProps {
  t: AppMessages;
  previewResume: ResumeData;
  templates: ResumeTemplateDefinition[];
  defaultTemplateId: string;
  isImporting: boolean;
  isCreating: boolean;
  settingDefaultTemplateId: string | null;
  onOpenTemplate: (templateId: string) => void;
  onSetDefaultTemplate: (templateId: string) => void;
  onCreateCustomTemplate: () => void;
  onImportTemplates: (file: File) => void;
  onDeleteTemplates: (templateIds: string[]) => void;
}

export function TemplateGallery({
  t,
  previewResume,
  templates,
  defaultTemplateId,
  isImporting,
  isCreating,
  settingDefaultTemplateId,
  onOpenTemplate,
  onSetDefaultTemplate,
  onCreateCustomTemplate,
  onImportTemplates,
  onDeleteTemplates,
}: TemplateGalleryProps) {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const { gridRef, pageSize } = useGalleryGridPageSize({ fixedItems: 0 });
  const gallery = useTemplateGalleryController({
    templates,
    pageSize,
    onDeleteTemplates,
  });

  function handleImportChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }
    onImportTemplates(file);
    event.target.value = "";
  }

  return (
    <section className="rounded-(--radius-workspace) border border-border bg-muted/35 p-3.5 text-foreground sm:p-4">
      <ConfirmActionDialog
        open={gallery.isDeleteDialogOpen}
        title={
          gallery.pendingDeleteIds.length > 1
            ? t.confirmDeleteTemplatesTitle
            : t.confirmDeleteTemplateTitle
        }
        description={
          gallery.pendingDeleteIds.length > 1
            ? t.confirmDeleteTemplatesDescription
            : t.confirmDeleteTemplateDescription
        }
        confirmLabel={t.confirmDeleteAction}
        cancelLabel={t.cancel}
        onConfirm={gallery.confirmDelete}
        onOpenChange={gallery.setDeleteDialogOpen}
      />
      <input
        ref={fileInputRef}
        type="file"
        accept=".json,application/json"
        className="hidden"
        disabled={isImporting}
        onChange={handleImportChange}
      />
      <GalleryToolbar
        searchLabel={t.searchTemplatesLabel}
        searchName="template-search"
        searchPlaceholder={t.searchTemplatesPlaceholder}
        searchValue={gallery.searchQuery}
        onSearchChange={gallery.setSearchQuery}
        isSelecting={gallery.isSelecting}
        onToggleSelecting={gallery.toggleSelecting}
        selectedCount={gallery.selectedTemplateIds.length}
        selectLabel={t.selectItems}
        cancelLabel={t.cancelSelection}
        bulkDeleteLabel={t.bulkDelete}
        onBulkDelete={() => gallery.requestDelete(gallery.selectedTemplateIds)}
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
              {isImporting ? t.importing : t.importTemplate}
            </Button>
            <Button
              type="button"
              disabled={isImporting || isCreating}
              onClick={onCreateCustomTemplate}
            >
              {isCreating ? (
                <Spinner data-icon="inline-start" aria-label={t.newTemplate} />
              ) : (
                <CopyPlus data-icon="inline-start" />
              )}
              {t.newTemplate}
            </Button>
          </>
        }
      />
      <div
        ref={gridRef}
        className="grid auto-rows-fr grid-cols-[repeat(auto-fit,minmax(208px,228px))] gap-4"
      >
        <TemplateGalleryGrid
          t={t}
          previewResume={previewResume}
          templates={gallery.paginatedTemplates}
          totalTemplateCount={templates.length}
          defaultTemplateId={defaultTemplateId}
          isSelecting={gallery.isSelecting}
          selectedIdSet={gallery.selectedIdSet}
          settingDefaultTemplateId={settingDefaultTemplateId}
          onOpenTemplate={onOpenTemplate}
          onRequestDelete={gallery.requestDelete}
          onSetDefaultTemplate={onSetDefaultTemplate}
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
