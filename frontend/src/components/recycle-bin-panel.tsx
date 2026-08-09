import { DeletedResumeTrashList } from "@/components/deleted-resume-trash-list";
import { DeletedTemplateTrashList } from "@/components/deleted-template-trash-list";
import { RecycleBinDeleteDialog } from "@/components/recycle-bin-delete-dialog";
import { TrashCountBadge } from "@/components/recycle-bin-item-row";
import type { RecycleBinPanelProps } from "@/components/recycle-bin-types";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useRecycleBinController } from "@/components/use-recycle-bin-controller";

export function RecycleBinPanel(props: RecycleBinPanelProps) {
  const {
    locale,
    t,
    deletedResumes,
    deletedTemplates,
    templates,
    templatePreviewResume,
  } = props;
  const controller = useRecycleBinController(props);

  return (
    <main className="flex-1 p-4">
      <RecycleBinDeleteDialog
        t={t}
        pendingAction={controller.dialog.pendingAction}
        isPending={controller.isBusy}
        isRunning={controller.dialog.isRunning}
        onConfirm={controller.dialog.confirm}
        onClose={controller.dialog.close}
      />

      <section className="rounded-(--radius-workspace) border border-border bg-background p-4 text-foreground">
        <Tabs
          value={controller.activeTab}
          onValueChange={controller.changeTab}
          className="gap-0"
        >
          <div className="flex flex-wrap items-center gap-3 border-b border-border/70">
            <TabsList
              variant="line"
              className="w-fit justify-start gap-8 p-0 group-data-[orientation=horizontal]/tabs:h-9"
            >
              <TabsTrigger
                value="resumes"
                disabled={controller.isBusy}
                className="h-9 min-w-0 flex-none rounded-none border-transparent px-0 py-0 text-sm font-semibold after:bottom-[-1px]!"
              >
                {t.resumeRecycleBin}
                <TrashCountBadge count={deletedResumes.length} />
              </TabsTrigger>
              <TabsTrigger
                value="templates"
                disabled={controller.isBusy}
                className="h-9 min-w-0 flex-none rounded-none border-transparent px-0 py-0 text-sm font-semibold after:bottom-[-1px]!"
              >
                {t.templateRecycleBin}
                <TrashCountBadge count={deletedTemplates.length} />
              </TabsTrigger>
            </TabsList>
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
            templatePreviewResume={templatePreviewResume}
            controller={controller}
          />
        </Tabs>
      </section>
    </main>
  );
}
