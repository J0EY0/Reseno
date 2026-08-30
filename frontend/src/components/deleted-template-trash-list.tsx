import { GalleryPagination } from "@/components/gallery-pagination";
import {
  EmptyTrashState,
  RecycleBinThumbnail,
  RecycleBinTable,
  type RecycleBinTableItem,
} from "@/components/recycle-bin-table";
import { formatTrashTimestamp } from "@/components/recycle-bin-format";
import { TabsContent } from "@/components/ui/tabs";
import type { RecycleBinController } from "@/components/use-recycle-bin-controller";
import type { AppMessages, Locale } from "@/i18n";
import type { ResumeData } from "@/types/resume";

export function DeletedTemplateTrashList({
  locale,
  t,
  templatePreviewResume,
  controller,
}: {
  locale: Locale;
  t: AppMessages;
  templatePreviewResume: ResumeData;
  controller: RecycleBinController;
}) {
  const items = controller.templates.items;
  const tableItems: RecycleBinTableItem[] = items.map((item) => ({
    id: item.id,
    thumbnail: (
      <RecycleBinThumbnail
        t={t}
        resume={templatePreviewResume}
        template={item}
        fontFamily={item.typography.fontFamily}
        fontSize={item.typography.fontSize}
        showEmptyTemplateImagePlaceholders
      />
    ),
    title: item.name,
    subtitle: item.description || t.templateDescriptionFallback,
    deletedAtText: formatTrashTimestamp(locale, item.deletedAt),
    isRestoring:
      controller.runningActionKey === `template-restore:${item.id}`,
    previewTarget: {
      variant: "template",
      title: item.name,
      resume: templatePreviewResume,
      template: item,
    },
  }));

  return (
    <TabsContent value="templates" className="mt-0">
      <div
        data-slot="trash-list-content"
        className="min-h-[390px] overflow-hidden"
      >
        {items.length > 0 ? (
          <>
            <RecycleBinTable
              items={tableItems}
              selectedIds={controller.templates.selectedPageIds}
              itemLabel={t.templateRecycleBin}
              deletedAtLabel={t.recycleBinDeletedAtLabel}
              selectAllLabel={t.selectAll}
              selectLabel={t.selectItems}
              previewLabel={t.preview}
              restoreLabel={t.restore}
              deleteLabel={t.deleteForever}
              actionsLabel={t.actions}
              emptyMessage={t.emptyTemplateTrash}
              disabled={controller.isBusy}
              onPreview={controller.preview.show}
              onSelectionChange={controller.templates.setSelectedIds}
              onRestore={controller.templates.restoreOne}
              onDelete={controller.templates.deleteOne}
            />
            <GalleryPagination
              currentPage={controller.currentPage}
              totalPages={controller.templates.totalPages}
              t={t}
              onPageChange={controller.changePage}
              disabled={controller.isBusy}
            />
          </>
        ) : (
          <EmptyTrashState>{t.emptyTemplateTrash}</EmptyTrashState>
        )}
      </div>
    </TabsContent>
  );
}
