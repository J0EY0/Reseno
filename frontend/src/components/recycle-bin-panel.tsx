import { RotateCcw, Trash2 } from "lucide-react";
import { useRef, useState, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";

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
import { Empty, EmptyDescription } from "@/components/ui/empty";
import { Spinner } from "@/components/ui/spinner";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { ViewTransitionBoundary } from "@/components/view-transition";

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

type TrashActionKey =
  | `resume-restore:${string}`
  | `template-restore:${string}`
  | "resume-delete"
  | "template-delete"
  | "resume-empty"
  | "template-empty";

function CountBadge({ count }: { count: number }) {
  return (
    <Badge
      variant="secondary"
      className="h-[18px] min-w-[18px] rounded-full px-1 text-[10px] leading-none text-muted-foreground"
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
    <div
      aria-hidden="true"
      className="relative h-[96px] w-[68px] shrink-0 overflow-hidden rounded-xl border border-zinc-200 bg-white shadow-sm"
    >
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
    <Empty className="min-h-[128px] p-4 md:p-4">
      <EmptyDescription className="font-medium">{children}</EmptyDescription>
    </Empty>
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
  isRestoring,
  disabled,
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
  isRestoring: boolean;
  disabled: boolean;
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
                disabled={disabled}
                onClick={onRestore}
              >
                {isRestoring ? (
                  <Spinner aria-label={restoreLabel} />
                ) : (
                  <RotateCcw />
                )}
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
                disabled={disabled}
                onClick={onDelete}
              >
                <Trash2 />
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
  onRestoreResume: (resumeIds: string[]) => Promise<boolean>;
  onDeleteResumeForever: (resumeIds: string[]) => Promise<boolean>;
  onEmptyResumeTrash: () => Promise<boolean>;
  onRestoreTemplate: (templateIds: string[]) => Promise<boolean>;
  onDeleteTemplateForever: (templateIds: string[]) => Promise<boolean>;
  onEmptyTemplateTrash: () => Promise<boolean>;
}) {
  const [searchParams, setSearchParams] = useSearchParams();
  const activeTab: RecycleBinTab =
    searchParams.get("tab") === "templates" ? "templates" : "resumes";
  const [pendingAction, setPendingAction] = useState<PendingTrashAction>(null);
  const [runningActionKey, setRunningActionKey] =
    useState<TrashActionKey | null>(null);
  // State drives feedback; the ref closes the same-render double-click gap.
  const runningActionRef = useRef<TrashActionKey | null>(null);

  const isDialogOpen = Boolean(pendingAction);
  const previewTemplates = [...templates, ...deletedTemplates];
  const activeItemCount =
    activeTab === "resumes" ? deletedResumes.length : deletedTemplates.length;
  const activeEmptyActionKey: TrashActionKey =
    activeTab === "resumes" ? "resume-empty" : "template-empty";

  function closeDialog() {
    setPendingAction(null);
  }

  async function runTrashAction(
    key: TrashActionKey,
    action: () => Promise<boolean>,
  ) {
    if (runningActionRef.current) {
      return false;
    }

    runningActionRef.current = key;
    setRunningActionKey(key);

    try {
      return await action();
    } finally {
      runningActionRef.current = null;
      setRunningActionKey(null);
    }
  }

  async function confirmAction() {
    if (!pendingAction) {
      return;
    }

    let succeeded = false;

    if (pendingAction.type === "resume-item") {
      succeeded = await runTrashAction("resume-delete", () =>
        onDeleteResumeForever(pendingAction.ids),
      );
    } else if (pendingAction.type === "template-item") {
      succeeded = await runTrashAction("template-delete", () =>
        onDeleteTemplateForever(pendingAction.ids),
      );
    } else if (pendingAction.type === "resume-empty") {
      succeeded = await runTrashAction("resume-empty", onEmptyResumeTrash);
    } else if (pendingAction.type === "template-empty") {
      succeeded = await runTrashAction("template-empty", onEmptyTemplateTrash);
    }

    if (succeeded) {
      closeDialog();
    }
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
        isPending={runningActionKey !== null}
        deferClose
        onOpenChange={(open) => {
          if (!open && !runningActionRef.current) {
            closeDialog();
          }
        }}
      />

      <section className="rounded-(--radius-workspace) border border-border bg-background p-4 text-foreground">
        <Tabs
          value={activeTab}
          onValueChange={(value) => {
            setSearchParams((current) => {
              const next = new URLSearchParams(current);

              if (value === "templates") {
                next.set("tab", "templates");
              } else {
                next.delete("tab");
              }

              return next;
            });
          }}
          className="gap-0"
        >
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/70">
            <TabsList
              variant="line"
              className="w-fit justify-start gap-8 p-0 group-data-[orientation=horizontal]/tabs:h-9"
            >
              <TabsTrigger
                value="resumes"
                className="h-9 min-w-0 flex-none rounded-none border-transparent px-0 py-0 text-sm font-semibold after:bottom-[-1px]!"
              >
                {t.resumeRecycleBin}
                <CountBadge count={deletedResumes.length} />
              </TabsTrigger>
              <TabsTrigger
                value="templates"
                className="h-9 min-w-0 flex-none rounded-none border-transparent px-0 py-0 text-sm font-semibold after:bottom-[-1px]!"
              >
                {t.templateRecycleBin}
                <CountBadge count={deletedTemplates.length} />
              </TabsTrigger>
            </TabsList>

            <Button
              type="button"
              variant="destructive"
              size="xs"
              className="h-7 self-start px-2.5 data-[hidden=true]:pointer-events-none data-[hidden=true]:opacity-0"
              data-hidden={activeItemCount === 0}
              aria-hidden={activeItemCount === 0}
              tabIndex={activeItemCount === 0 ? -1 : undefined}
              disabled={activeItemCount === 0 || runningActionKey !== null}
              onClick={requestEmptyActiveTab}
            >
              {runningActionKey === activeEmptyActionKey ? (
                <Spinner data-icon="inline-start" aria-label={t.emptyTrash} />
              ) : (
                <Trash2 data-icon="inline-start" />
              )}
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

                  const restoreActionKey = `resume-restore:${item.id}` as const;

                  return (
                    <ViewTransitionBoundary
                      key={item.id}
                      enter="fade-in"
                      exit="fade-out"
                      default="none"
                    >
                      <TrashItemRow
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
                        isRestoring={runningActionKey === restoreActionKey}
                        disabled={runningActionKey !== null}
                        onRestore={() => {
                          void runTrashAction(restoreActionKey, () =>
                            onRestoreResume([item.id]),
                          );
                        }}
                        onDelete={() =>
                          setPendingAction({
                            type: "resume-item",
                            ids: [item.id],
                          })
                        }
                      />
                    </ViewTransitionBoundary>
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

                  const restoreActionKey = `template-restore:${item.id}` as const;

                  return (
                    <ViewTransitionBoundary
                      key={item.id}
                      enter="fade-in"
                      exit="fade-out"
                      default="none"
                    >
                      <TrashItemRow
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
                        subtitle={
                          item.description || t.templateDescriptionFallback
                        }
                        deletedAt={deletedAt}
                        deletedAtText={`${t.recycleBinDeletedAtPrefix} ${deletedAt}`}
                        restoreLabel={t.restore}
                        deleteLabel={t.deleteForever}
                        isRestoring={runningActionKey === restoreActionKey}
                        disabled={runningActionKey !== null}
                        onRestore={() => {
                          void runTrashAction(restoreActionKey, () =>
                            onRestoreTemplate([item.id]),
                          );
                        }}
                        onDelete={() =>
                          setPendingAction({
                            type: "template-item",
                            ids: [item.id],
                          })
                        }
                      />
                    </ViewTransitionBoundary>
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
