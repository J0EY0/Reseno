import { RotateCcw, Trash2 } from "lucide-react";
import { useState, type ReactNode } from "react";

import type { AppMessages, Locale } from "@/i18n";
import { getTemplateById } from "@/lib/templates";
import type {
  DeletedResumeTemplateDefinition,
  DeletedResumeWorkspaceItem,
  ResumeData,
  ResumeTemplateDefinition,
} from "@/types/resume";

import { ConfirmActionDialog } from "@/components/confirm-action-dialog";
import { ResumePreview } from "@/components/preview/resume-preview";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

const trashTableGridClassName =
  "md:grid-cols-[minmax(360px,1fr)_160px_84px]";

function formatAt(locale: Locale, value: string) {
  return new Intl.DateTimeFormat(locale === "zh" ? "zh-CN" : "en-US", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

type RecycleBinTab = "resumes" | "templates";

type PendingTrashAction =
  | { type: "resume-item"; ids: string[] }
  | { type: "template-item"; ids: string[] }
  | { type: "resume-empty" }
  | { type: "template-empty" }
  | null;

function CountBadge({ count }: { count: number }) {
  return (
    <Badge
      variant="secondary"
      className="h-5 min-w-5 rounded-full px-1.5 text-[11px] text-muted-foreground"
    >
      {count}
    </Badge>
  );
}

function PreviewThumbnail({
  t,
  resume,
  template,
  fontFamily,
  fontSize,
}: {
  t: AppMessages;
  resume: ResumeData;
  template: ResumeTemplateDefinition;
  fontFamily: ResumeTemplateDefinition["typography"]["fontFamily"];
  fontSize: number;
}) {
  return (
    <div className="relative h-[96px] w-[68px] shrink-0 overflow-hidden rounded-xl border border-zinc-200 bg-white shadow-sm">
      <div
        className="pointer-events-none absolute left-0 top-0 origin-top-left scale-[0.084]"
        style={{ width: "210mm", height: "297mm" }}
      >
        <ResumePreview
          t={t}
          resume={resume}
          fontFamily={fontFamily}
          fontSize={fontSize}
          template={template}
          variant="thumbnail"
        />
      </div>
    </div>
  );
}

function EmptyTrashState({ children }: { children: string }) {
  return (
    <div className="flex min-h-[128px] items-center justify-center text-sm font-medium text-muted-foreground">
      {children}
    </div>
  );
}

function TrashItemRow({
  thumbnail,
  title,
  subtitle,
  deletedAt,
  deletedAtText,
  restoreLabel,
  deleteLabel,
  onRestore,
  onDelete,
}: {
  thumbnail: ReactNode;
  title: string;
  subtitle: string;
  deletedAt: string;
  deletedAtText: string;
  restoreLabel: string;
  deleteLabel: string;
  onRestore: () => void;
  onDelete: () => void;
}) {
  return (
    <div
      className={`grid gap-4 border-b border-border/60 px-6 py-4 last:border-b-0 md:items-center ${trashTableGridClassName}`}
    >
      <div className="flex min-w-0 items-center gap-4">
        {thumbnail}
        <div className="min-w-0">
          <p className="truncate text-base font-semibold text-foreground">
            {title}
          </p>
          {subtitle ? (
            <p className="mt-1 truncate text-sm text-muted-foreground">
              {subtitle}
            </p>
          ) : null}
          <p className="mt-1 text-sm text-muted-foreground md:hidden">
            {deletedAtText}
          </p>
        </div>
      </div>

      <p className="hidden text-center text-sm text-muted-foreground md:block">
        {deletedAt}
      </p>

      <div className="flex flex-wrap items-center gap-1 md:justify-center">
        <TooltipProvider delayDuration={160}>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="size-8 rounded-md text-muted-foreground hover:bg-muted hover:text-foreground"
                aria-label={restoreLabel}
                onClick={onRestore}
              >
                <RotateCcw className="size-3.5" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>{restoreLabel}</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="size-8 rounded-md text-red-500 hover:bg-muted hover:text-red-600"
                aria-label={deleteLabel}
                onClick={onDelete}
              >
                <Trash2 className="size-3.5" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>{deleteLabel}</TooltipContent>
          </Tooltip>
        </TooltipProvider>
      </div>
    </div>
  );
}

export function RecycleBinPanel({
  locale,
  t,
  deletedResumes,
  deletedTemplates,
  templates,
  defaultTemplateId,
  templatePreviewResume,
  onRestoreResume,
  onDeleteResumeForever,
  onEmptyResumeTrash,
  onRestoreTemplate,
  onDeleteTemplateForever,
  onEmptyTemplateTrash,
}: {
  locale: Locale;
  t: AppMessages;
  deletedResumes: DeletedResumeWorkspaceItem[];
  deletedTemplates: DeletedResumeTemplateDefinition[];
  templates: ResumeTemplateDefinition[];
  defaultTemplateId: string;
  templatePreviewResume: ResumeData;
  onRestoreResume: (resumeIds: string[]) => void;
  onDeleteResumeForever: (resumeIds: string[]) => void;
  onEmptyResumeTrash: () => void;
  onRestoreTemplate: (templateIds: string[]) => void;
  onDeleteTemplateForever: (templateIds: string[]) => void;
  onEmptyTemplateTrash: () => void;
}) {
  const [activeTab, setActiveTab] = useState<RecycleBinTab>("resumes");
  const [pendingAction, setPendingAction] = useState<PendingTrashAction>(null);

  const isDialogOpen = Boolean(pendingAction);
  const previewTemplates = [...templates, ...deletedTemplates];
  const activeItemCount =
    activeTab === "resumes" ? deletedResumes.length : deletedTemplates.length;

  function closeDialog() {
    setPendingAction(null);
  }

  function confirmAction() {
    if (!pendingAction) {
      return;
    }

    if (pendingAction.type === "resume-item") {
      onDeleteResumeForever(pendingAction.ids);
    } else if (pendingAction.type === "template-item") {
      onDeleteTemplateForever(pendingAction.ids);
    } else if (pendingAction.type === "resume-empty") {
      onEmptyResumeTrash();
    } else if (pendingAction.type === "template-empty") {
      onEmptyTemplateTrash();
    }

    closeDialog();
  }

  function requestEmptyActiveTab() {
    setPendingAction(
      activeTab === "resumes"
        ? { type: "resume-empty" }
        : { type: "template-empty" },
    );
  }

  const dialogTitle =
    pendingAction?.type === "resume-item"
      ? t.confirmDeleteResumeForeverTitle
      : pendingAction?.type === "template-item"
        ? t.confirmDeleteTemplateForeverTitle
        : pendingAction?.type === "resume-empty"
          ? t.confirmEmptyResumeTrashTitle
          : pendingAction?.type === "template-empty"
            ? t.confirmEmptyTemplateTrashTitle
            : "";

  const dialogDescription =
    pendingAction?.type === "resume-item"
      ? t.confirmDeleteResumeForeverDescription
      : pendingAction?.type === "template-item"
        ? t.confirmDeleteTemplateForeverDescription
        : pendingAction?.type === "resume-empty"
          ? t.confirmEmptyResumeTrashDescription
          : pendingAction?.type === "template-empty"
            ? t.confirmEmptyTemplateTrashDescription
            : "";

  const dialogActionLabel =
    pendingAction?.type === "resume-empty" || pendingAction?.type === "template-empty"
      ? t.emptyTrash
      : t.deleteForever;

  return (
    <main className="flex-1 p-4">
      <ConfirmActionDialog
        open={isDialogOpen}
        title={dialogTitle}
        description={dialogDescription}
        confirmLabel={dialogActionLabel}
        cancelLabel={t.cancel}
        onConfirm={confirmAction}
        onOpenChange={(open) => {
          if (!open) {
            closeDialog();
          }
        }}
      />

      <section className="rounded-[26px] border border-border bg-background p-4 text-foreground sm:p-6">
        <Tabs
          value={activeTab}
          onValueChange={(value) => setActiveTab(value as RecycleBinTab)}
          className="gap-0"
        >
          <div className="flex flex-wrap items-end justify-between gap-3 border-b border-border/70">
            <TabsList className="h-auto gap-8 rounded-none border-0 bg-transparent p-0">
              <TabsTrigger
                value="resumes"
                className="min-w-0 rounded-none border-b-2 border-transparent bg-transparent px-0 pb-3 pt-0 text-base font-semibold text-muted-foreground data-[state=active]:border-foreground data-[state=active]:bg-transparent data-[state=active]:text-foreground"
              >
                {t.resumeRecycleBin}
                <CountBadge count={deletedResumes.length} />
              </TabsTrigger>
              <TabsTrigger
                value="templates"
                className="min-w-0 rounded-none border-b-2 border-transparent bg-transparent px-0 pb-3 pt-0 text-base font-semibold text-muted-foreground data-[state=active]:border-foreground data-[state=active]:bg-transparent data-[state=active]:text-foreground"
              >
                {t.templateRecycleBin}
                <CountBadge count={deletedTemplates.length} />
              </TabsTrigger>
            </TabsList>

            <Button
              type="button"
              variant="destructive"
              className="mb-3 h-10 rounded-lg px-4 font-semibold data-[hidden=true]:pointer-events-none data-[hidden=true]:opacity-0"
              data-hidden={activeItemCount === 0}
              aria-hidden={activeItemCount === 0}
              tabIndex={activeItemCount === 0 ? -1 : undefined}
              onClick={requestEmptyActiveTab}
            >
              <Trash2 className="size-4" />
              {t.emptyTrash}
            </Button>
          </div>

          <TabsContent value="resumes" className="mt-5">
            <div className="overflow-hidden">
              {deletedResumes.length > 0 ? (
                deletedResumes.map((item) => {
                  const title =
                    item.title || item.resume.basic.name || t.untitledResume;
                  const deletedAt = formatAt(locale, item.deletedAt);
                  const template = getTemplateById(
                    previewTemplates,
                    item.template,
                    defaultTemplateId,
                  );

                  return (
                    <TrashItemRow
                      key={item.id}
                      thumbnail={
                        <PreviewThumbnail
                          t={t}
                          resume={item.resume}
                          template={template}
                          fontFamily={item.typography?.fontFamily ?? "inter"}
                          fontSize={item.typography?.fontSize ?? 15}
                        />
                      }
                      title={title}
                      subtitle={
                        item.resume.basic.headline ||
                        item.resume.basic.email ||
                        item.resume.basic.phone
                      }
                      deletedAt={deletedAt}
                      deletedAtText={`${t.recycleBinDeletedAtPrefix} ${deletedAt}`}
                      restoreLabel={t.restore}
                      deleteLabel={t.deleteForever}
                      onRestore={() => onRestoreResume([item.id])}
                      onDelete={() =>
                        setPendingAction({
                          type: "resume-item",
                          ids: [item.id],
                        })
                      }
                    />
                  );
                })
              ) : (
                <EmptyTrashState>{t.emptyResumeTrash}</EmptyTrashState>
              )}
            </div>
          </TabsContent>

          <TabsContent value="templates" className="mt-5">
            <div className="overflow-hidden">
              {deletedTemplates.length > 0 ? (
                deletedTemplates.map((item) => {
                  const deletedAt = formatAt(locale, item.deletedAt);

                  return (
                    <TrashItemRow
                      key={item.id}
                      thumbnail={
                        <PreviewThumbnail
                          t={t}
                          resume={templatePreviewResume}
                          template={item}
                          fontFamily={item.typography.fontFamily}
                          fontSize={item.typography.fontSize}
                        />
                      }
                      title={item.name}
                      subtitle={item.description || t.templateDescriptionFallback}
                      deletedAt={deletedAt}
                      deletedAtText={`${t.recycleBinDeletedAtPrefix} ${deletedAt}`}
                      restoreLabel={t.restore}
                      deleteLabel={t.deleteForever}
                      onRestore={() => onRestoreTemplate([item.id])}
                      onDelete={() =>
                        setPendingAction({
                          type: "template-item",
                          ids: [item.id],
                        })
                      }
                    />
                  );
                })
              ) : (
                <EmptyTrashState>{t.emptyTemplateTrash}</EmptyTrashState>
              )}
            </div>
          </TabsContent>
        </Tabs>
      </section>
    </main>
  );
}
