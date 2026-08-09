import { GalleryPagination } from "@/components/gallery-pagination";
import {
  EmptyTrashState,
  RecycleBinThumbnail,
  TrashItemRow,
  TrashSelectionToolbar,
} from "@/components/recycle-bin-item-row";
import { formatTrashTimestamp } from "@/components/recycle-bin-format";
import { TabsContent } from "@/components/ui/tabs";
import type { RecycleBinController } from "@/components/use-recycle-bin-controller";
import { ViewTransitionBoundary } from "@/components/view-transition";
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

  return (
    <TabsContent value="templates" className="mt-0">
      <div className="overflow-hidden">
        {items.length > 0 ? (
          <>
            <TrashSelectionToolbar
              selectionId="select-all-deleted-templates"
              selectAllLabel={t.selectAll}
              restoreLabel={t.restoreSelected}
              deleteLabel={t.deleteSelectedForever}
              selectedCount={controller.templates.selectedPageIds.length}
              itemCount={items.length}
              onSelectAll={controller.templates.selectAll}
              onRestore={controller.templates.restoreSelected}
              onDelete={controller.templates.deleteSelected}
              isRestoring={
                controller.runningActionKey === "template-restore-selected"
              }
              disabled={controller.isBusy}
            />

            {items.map((item) => (
              <ViewTransitionBoundary
                key={item.id}
                enter="fade-in"
                exit="fade-out"
                default="none"
              >
                <TrashItemRow
                  thumbnail={
                    <RecycleBinThumbnail
                      t={t}
                      resume={templatePreviewResume}
                      template={item}
                      fontFamily={item.typography.fontFamily}
                      fontSize={item.typography.fontSize}
                      showEmptyTemplateImagePlaceholders
                    />
                  }
                  title={item.name}
                  subtitle={item.description || t.templateDescriptionFallback}
                  deletedAtText={`${t.recycleBinDeletedAtPrefix} ${formatTrashTimestamp(locale, item.deletedAt)}`}
                  restoreLabel={t.restore}
                  deleteLabel={t.deleteForever}
                  isRestoring={
                    controller.runningActionKey ===
                    `template-restore:${item.id}`
                  }
                  disabled={controller.isBusy}
                  selected={controller.templates.selectedIdSet.has(item.id)}
                  selectLabel={t.selectItems}
                  onSelectedChange={(selected) =>
                    controller.templates.toggleSelected(item.id, selected)
                  }
                  onRestore={() => controller.templates.restoreOne(item.id)}
                  onDelete={() => controller.templates.deleteOne(item.id)}
                />
              </ViewTransitionBoundary>
            ))}
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
