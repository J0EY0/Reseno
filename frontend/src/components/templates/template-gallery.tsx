import { CopyPlus, FileUp } from "lucide-react";
import { useRef, type ChangeEvent } from "react";

import { ConfirmActionDialog } from "@/components/confirm-action-dialog";
import { GalleryPagination } from "@/components/gallery-pagination";
import { GalleryToolbar } from "@/components/gallery-toolbar";
import { useResumeThumbnailFonts } from "@/components/preview/resume-thumbnail-fonts";
import { useGalleryGridPageSize } from "@/components/use-gallery-grid-page-size";
import { Button } from "@/components/ui/button";
import { Empty, EmptyDescription } from "@/components/ui/empty";
import { Spinner } from "@/components/ui/spinner";
import type { AppMessages } from "@/i18n";
import type { TemplatePreviewResumes } from "@/lib/template-preview-resume";
import type {
  DocumentLocale,
  ResumeTemplateDefinition,
} from "@/types/resume";

import { TemplateGalleryGrid } from "./template-gallery-grid";
import { TemplateLocaleSelect } from "./template-locale-select";
import { useTemplateGalleryController } from "./use-template-gallery-controller";

interface TemplateGalleryProps {
  t: AppMessages;
  previewMessages: AppMessages | null;
  previewResumes: TemplatePreviewResumes | null;
  templates: ResumeTemplateDefinition[];
  defaultTemplateId: string;
  templateLocale: DocumentLocale;
  isImporting: boolean;
  isCreating: boolean;
  openingTemplateId: string | null;
  settingDefaultTemplateId: string | null;
  onPreloadTemplateDetail: () => void;
  onOpenTemplate: (templateId: string) => void;
  onSetDefaultTemplate: (templateId: string) => void;
  onTemplateLocaleChange: (locale: DocumentLocale) => void;
  onCreateCustomTemplate: () => void;
  onImportTemplates: (file: File) => void;
  onDeleteTemplates: (templateIds: string[]) => Promise<string[]>;
}

export function TemplateGallery({
  t,
  previewMessages,
  previewResumes,
  templates,
  defaultTemplateId,
  templateLocale,
  isImporting,
  isCreating,
  openingTemplateId,
  settingDefaultTemplateId,
  onPreloadTemplateDetail,
  onOpenTemplate,
  onSetDefaultTemplate,
  onTemplateLocaleChange,
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
  useResumeThumbnailFonts(
    gallery.paginatedTemplates.map(
      (template) => template.typography.fontFamily,
    ),
  );

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
            <TemplateLocaleSelect
              disabled={settingDefaultTemplateId !== null}
              chineseLabel={t.chineseTemplate}
              englishLabel={t.englishTemplate}
              messages={t}
              value={templateLocale}
              onValueChange={onTemplateLocaleChange}
            />
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
              aria-label={isCreating ? t.creating : t.newTemplate}
              aria-busy={isCreating || undefined}
              onClick={onCreateCustomTemplate}
            >
              <CopyPlus data-icon="inline-start" />
              {t.newTemplate}
            </Button>
          </>
        }
      />
      {gallery.paginatedTemplates.length === 0 ? (
        <Empty className="min-h-[390px]">
          <EmptyDescription className="font-medium">
            {templates.length === 0
              ? t.emptyTemplates
              : t.emptyTemplateSearch}
          </EmptyDescription>
        </Empty>
      ) : null}
      <div
        ref={gridRef}
        data-slot="gallery-grid"
        className="grid auto-rows-fr grid-cols-[repeat(auto-fill,minmax(208px,228px))] justify-center gap-4"
      >
        <TemplateGalleryGrid
          t={t}
          previewMessages={previewMessages}
          previewResumes={previewResumes}
          templates={gallery.paginatedTemplates}
          defaultTemplateId={defaultTemplateId}
          isSelecting={gallery.isSelecting}
          selectedIdSet={gallery.selectedIdSet}
          openingTemplateId={openingTemplateId}
          settingDefaultTemplateId={settingDefaultTemplateId}
          onPreloadTemplateDetail={onPreloadTemplateDetail}
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
