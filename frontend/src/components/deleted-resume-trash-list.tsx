import type { RecycleBinController } from "@/components/use-recycle-bin-controller";
import { GalleryPagination } from "@/components/gallery-pagination";
import {
  EmptyTrashState,
  RecycleBinThumbnail,
  RecycleBinTable,
  type RecycleBinTableItem,
} from "@/components/recycle-bin-table";
import { formatTrashTimestamp } from "@/components/recycle-bin-format";
import { TabsContent } from "@/components/ui/tabs";
import type { AppMessages, Locale } from "@/i18n";
import { getRichTextPlainText } from "@/lib/rich-text";
import { createTemplateSettings, getTemplateById } from "@/lib/templates";
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
  const tableItems: RecycleBinTableItem[] = items.map((item) => {
    const title =
      item.title || getRichTextPlainText(item.resume.basic.name) || t.untitledResume;
    const baseTemplate = getTemplateById(previewTemplates, item.template);
    const template: ResumeTemplateDefinition = {
      ...baseTemplate,
      settings: createTemplateSettings(baseTemplate.preset, {
        ...baseTemplate.settings,
        ...(item.templateSettings ?? {}),
      }),
    };

    return {
      id: item.id,
      thumbnail: (
        <RecycleBinThumbnail
          t={t}
          resume={item.resume}
          template={template}
          fontFamily={item.typography.fontFamily}
          fontSize={item.typography.fontSize}
          documentLocale={item.documentLocale}
        />
      ),
      title,
      subtitle:
        getRichTextPlainText(item.resume.basic.headline) ||
        item.resume.basic.email ||
        item.resume.basic.phone,
      deletedAtText: formatTrashTimestamp(locale, item.deletedAt),
      isRestoring:
        controller.runningActionKey === `resume-restore:${item.id}`,
      previewTarget: {
        variant: "resume",
        title,
        documentLocale: item.documentLocale,
        resume: item.resume,
        template,
        typography: item.typography,
      },
    };
  });

  return (
    <TabsContent value="resumes" className="mt-0">
      <div
        data-slot="trash-list-content"
        className="min-h-[390px] overflow-hidden"
      >
        {items.length > 0 ? (
          <>
            <RecycleBinTable
              items={tableItems}
              selectedIds={controller.resumes.selectedPageIds}
              itemLabel={t.resumeRecycleBin}
              deletedAtLabel={t.recycleBinDeletedAtLabel}
              selectAllLabel={t.selectAll}
              selectLabel={t.selectItems}
              previewLabel={t.preview}
              restoreLabel={t.restore}
              deleteLabel={t.deleteTrashItemAction}
              actionsLabel={t.actions}
              emptyMessage={t.emptyResumeTrash}
              disabled={controller.isBusy}
              onPreview={controller.preview.show}
              onSelectionChange={controller.resumes.setSelectedIds}
              onRestore={controller.resumes.restoreOne}
              onDelete={controller.resumes.deleteOne}
            />
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
