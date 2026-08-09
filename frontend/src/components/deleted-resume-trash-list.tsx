import type { RecycleBinController } from "@/components/use-recycle-bin-controller";
import { GalleryPagination } from "@/components/gallery-pagination";
import {
  EmptyTrashState,
  RecycleBinThumbnail,
  TrashItemRow,
  TrashSelectionToolbar,
} from "@/components/recycle-bin-item-row";
import { formatTrashTimestamp } from "@/components/recycle-bin-format";
import { TabsContent } from "@/components/ui/tabs";
import { ViewTransitionBoundary } from "@/components/view-transition";
import type { AppMessages, Locale } from "@/i18n";
import { getTemplateById } from "@/lib/templates";
import type {
  DeletedResumeTemplateDefinition,
  ResumeTemplateDefinition,
} from "@/types/resume";

export function DeletedResumeTrashList({
  locale,
  t,
  templates,
  deletedTemplates,
  controller,
}: {
  locale: Locale;
  t: AppMessages;
  templates: ResumeTemplateDefinition[];
  deletedTemplates: DeletedResumeTemplateDefinition[];
  controller: RecycleBinController;
}) {
  const items = controller.resumes.items;
  const previewTemplates = [...templates, ...deletedTemplates];

  return (
    <TabsContent value="resumes" className="mt-0">
      <div className="overflow-hidden">
        {items.length > 0 ? (
          <>
            <TrashSelectionToolbar
              selectionId="select-all-deleted-resumes"
              selectAllLabel={t.selectAll}
              restoreLabel={t.restoreSelected}
              deleteLabel={t.deleteSelectedForever}
              selectedCount={controller.resumes.selectedPageIds.length}
              itemCount={items.length}
              onSelectAll={controller.resumes.selectAll}
              onRestore={controller.resumes.restoreSelected}
              onDelete={controller.resumes.deleteSelected}
              isRestoring={
                controller.runningActionKey === "resume-restore-selected"
              }
              disabled={controller.isBusy}
            />

            {items.map((item) => {
              const title =
                item.title || item.resume.basic.name || t.untitledResume;
              const template = getTemplateById(
                previewTemplates,
                item.template,
              );

              return (
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
                        resume={item.resume}
                        template={template}
                        fontFamily={item.typography.fontFamily}
                        fontSize={item.typography.fontSize}
                      />
                    }
                    title={title}
                    subtitle={
                      item.resume.basic.headline ||
                      item.resume.basic.email ||
                      item.resume.basic.phone
                    }
                    deletedAtText={`${t.recycleBinDeletedAtPrefix} ${formatTrashTimestamp(locale, item.deletedAt)}`}
                    restoreLabel={t.restore}
                    deleteLabel={t.deleteForever}
                    isRestoring={
                      controller.runningActionKey ===
                      `resume-restore:${item.id}`
                    }
                    disabled={controller.isBusy}
                    selected={controller.resumes.selectedIdSet.has(item.id)}
                    selectLabel={t.selectItems}
                    onSelectedChange={(selected) =>
                      controller.resumes.toggleSelected(item.id, selected)
                    }
                    onRestore={() => controller.resumes.restoreOne(item.id)}
                    onDelete={() => controller.resumes.deleteOne(item.id)}
                  />
                </ViewTransitionBoundary>
              );
            })}
            <GalleryPagination
              currentPage={controller.currentPage}
              totalPages={controller.resumes.totalPages}
              t={t}
              onPageChange={controller.changePage}
              disabled={controller.isBusy}
            />
          </>
        ) : (
          <EmptyTrashState>{t.emptyResumeTrash}</EmptyTrashState>
        )}
      </div>
    </TabsContent>
  );
}
