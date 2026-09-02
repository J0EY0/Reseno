import { DeletedResumeTrashList } from "@/components/deleted-resume-trash-list";
import { DeletedTemplateTrashList } from "@/components/deleted-template-trash-list";
import { useResumeThumbnailFonts } from "@/components/preview/resume-thumbnail-fonts";
import { RecycleBinDeleteDialog } from "@/components/recycle-bin-delete-dialog";
import { RecycleBinPreviewDialog } from "@/components/recycle-bin-preview-dialog";
import {
  TrashBulkActions,
  TrashCountBadge,
} from "@/components/recycle-bin-table";
import type { RecycleBinPanelProps } from "@/components/recycle-bin-types";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useRecycleBinController } from "@/components/use-recycle-bin-controller";
import { cn } from "@/lib/utils";

export function RecycleBinPanel(props: RecycleBinPanelProps) {
  const {
    locale,
    t,
    deletedResumes,
    deletedTemplates,
    templates,
    templatePreviewResumes,
  } = props;
  const controller = useRecycleBinController(props);
  useResumeThumbnailFonts(
    controller.activeTab === "resumes"
      ? controller.resumes.items.map((item) => item.typography.fontFamily)
      : controller.templates.items.map(
          (template) => template.typography.fontFamily,
        ),
  );
  const activeCollection =
    controller.activeTab === "resumes"
      ? controller.resumes
      : controller.templates;

  return (
    <div className="flex-1 p-4">
      <RecycleBinDeleteDialog
        t={t}
        pendingAction={controller.dialog.pendingAction}
        isPending={controller.isBusy}
        isRunning={controller.dialog.isRunning}
        onConfirm={controller.dialog.confirm}
        onClose={controller.dialog.close}
      />
      <RecycleBinPreviewDialog
        t={t}
        target={controller.preview.target}
        open={controller.preview.open}
        onClose={controller.preview.close}
        restoreFocus={controller.preview.restoreFocus}
      />

      <section
        data-slot="recycle-bin-panel"
        className="rounded-(--radius-workspace) border border-border bg-muted/35 p-4 text-foreground"
      >
        <Tabs
          value={controller.activeTab}
          onValueChange={controller.changeTab}
          className="gap-0"
        >
          <div className="flex min-h-9 flex-wrap items-center gap-3 pb-4">
            <TabsList className="relative grid grid-cols-2">
              <span
                aria-hidden="true"
                className={cn(
                  "pointer-events-none absolute inset-y-[3.5px] left-[3px] w-[calc(50%_-_3px)] rounded-md border border-transparent bg-background shadow-sm transition-transform duration-200 ease-out motion-reduce:transition-none dark:border-input dark:bg-input/30",
                  controller.activeTab === "templates" && "translate-x-full",
                )}
              />
              <TabsTrigger
                value="resumes"
                disabled={controller.isBusy}
                className="group/trash-tab data-[state=active]:border-transparent! data-[state=active]:bg-transparent! data-[state=active]:shadow-none!"
              >
                {t.resumeRecycleBin}
                <TrashCountBadge count={deletedResumes.length} />
              </TabsTrigger>
              <TabsTrigger
                value="templates"
                disabled={controller.isBusy}
                className="group/trash-tab data-[state=active]:border-transparent! data-[state=active]:bg-transparent! data-[state=active]:shadow-none!"
              >
                {t.templateRecycleBin}
                <TrashCountBadge count={deletedTemplates.length} />
              </TabsTrigger>
            </TabsList>
            <TrashBulkActions
              restoreLabel={t.restoreSelected}
              deleteLabel={t.deleteSelectedForever}
              selectedCount={activeCollection.selectedPageIds.length}
              onRestore={activeCollection.restoreSelected}
              onDelete={activeCollection.deleteSelected}
              isRestoring={
                controller.runningActionKey ===
                `${controller.activeTab === "resumes" ? "resume" : "template"}-restore-selected`
              }
              disabled={controller.isBusy}
            />
          </div>

          <DeletedResumeTrashList
            locale={locale}
            t={t}
            templates={templates}
            deletedTemplates={deletedTemplates}
            controller={controller}
          />
          <DeletedTemplateTrashList
            locale={locale}
            t={t}
            templatePreviewResumes={templatePreviewResumes}
            controller={controller}
          />
        </Tabs>
      </section>
    </div>
  );
}
