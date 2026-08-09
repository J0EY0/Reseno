import { RotateCcw, Trash2 } from "lucide-react";
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
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
import { GalleryPagination } from "@/components/gallery-pagination";
import { ResumePreview } from "@/components/preview/resume-preview";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Empty, EmptyDescription } from "@/components/ui/empty";
import { Spinner } from "@/components/ui/spinner";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ViewTransitionBoundary } from "@/components/view-transition";
import { cn } from "@/lib/utils";

function formatAt(locale: Locale, value: string) {
  return new Intl.DateTimeFormat(locale === "zh" ? "zh-CN" : "en-US", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

type RecycleBinTab = "resumes" | "templates";

// Recycle-bin rows have a stable height, so a fixed page size keeps the list
// predictable without coupling pagination to viewport measurements.
const TRASH_PAGE_SIZE = 10;

type PendingTrashAction =
  | { type: "resume-item"; ids: string[] }
  | { type: "template-item"; ids: string[] }
  | null;

type TrashActionKey =
  | `resume-restore:${string}`
  | `template-restore:${string}`
  | "resume-restore-selected"
  | "template-restore-selected"
  | "resume-delete"
  | "template-delete";

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
  showEmptyTemplateImagePlaceholders = false,
}: {
  t: AppMessages;
  resume: ResumeData;
  template: ResumeTemplateDefinition;
  fontFamily: ResumeTemplateDefinition["typography"]["fontFamily"];
  fontSize: number;
  showEmptyTemplateImagePlaceholders?: boolean;
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
          showEmptyTemplateImagePlaceholders={
            showEmptyTemplateImagePlaceholders
          }
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

function TrashSelectionToolbar({
  selectionId,
  selectAllLabel,
  restoreLabel,
  deleteLabel,
  selectedCount,
  itemCount,
  onSelectAll,
  onRestore,
  onDelete,
  isRestoring,
  disabled,
}: {
  selectionId: string;
  selectAllLabel: string;
  restoreLabel: string;
  deleteLabel: string;
  selectedCount: number;
  itemCount: number;
  onSelectAll: (selected: boolean) => void;
  onRestore: () => void;
  onDelete: () => void;
  isRestoring: boolean;
  disabled: boolean;
}) {
  const allSelected = itemCount > 0 && selectedCount === itemCount;
  const partlySelected = selectedCount > 0 && !allSelected;

  return (
    <div className="flex min-h-16 flex-wrap items-center gap-3 border-b border-border/60 bg-background px-6 py-4">
      <label
        htmlFor={selectionId}
        className="mr-2 inline-flex cursor-pointer items-center gap-2.5 text-sm font-medium"
      >
        <Checkbox
          id={selectionId}
          checked={allSelected ? true : partlySelected ? "indeterminate" : false}
          disabled={disabled}
          onCheckedChange={(checked) => onSelectAll(checked === true)}
        />
        {selectAllLabel}
      </label>

      <Button
        type="button"
        variant="outline"
        size="default"
        disabled={disabled || selectedCount === 0}
        onClick={onRestore}
      >
        {isRestoring ? (
          <Spinner data-icon="inline-start" aria-label={restoreLabel} />
        ) : (
          <RotateCcw data-icon="inline-start" />
        )}
        {restoreLabel}
      </Button>
      <Button
        type="button"
        variant="outline"
        size="default"
        className="text-destructive hover:bg-destructive/10 hover:text-destructive disabled:text-muted-foreground"
        disabled={disabled || selectedCount === 0}
        onClick={onDelete}
      >
        <Trash2 data-icon="inline-start" />
        {deleteLabel}
      </Button>
    </div>
  );
}

function TrashItemRow({
  thumbnail,
  title,
  subtitle,
  deletedAtText,
  restoreLabel,
  deleteLabel,
  onRestore,
  onDelete,
  isRestoring,
  disabled,
  selected,
  selectLabel,
  onSelectedChange,
}: {
  thumbnail: ReactNode;
  title: string;
  subtitle: string;
  deletedAtText: string;
  restoreLabel: string;
  deleteLabel: string;
  onRestore: () => void;
  onDelete: () => void;
  isRestoring: boolean;
  disabled: boolean;
  selected: boolean;
  selectLabel: string;
  onSelectedChange: (selected: boolean) => void;
}) {
  return (
    <div
      className={cn(
        "grid grid-cols-[auto_minmax(0,1fr)] gap-4 border-b border-border/60 px-6 py-4 transition-colors last:border-b-0 md:grid-cols-[auto_minmax(0,1fr)_auto] md:items-center",
        selected && "bg-muted/25",
      )}
    >
      <Checkbox
        checked={selected}
        disabled={disabled}
        aria-label={`${selectLabel}: ${title}`}
        onCheckedChange={(checked) => onSelectedChange(checked === true)}
      />

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
          <p className="mt-1 text-sm text-muted-foreground">
            {deletedAtText}
          </p>
        </div>
      </div>

      <div className="col-start-2 flex flex-wrap items-center gap-2 md:col-start-3 md:justify-end">
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={disabled}
          onClick={onRestore}
        >
          {isRestoring ? (
            <Spinner data-icon="inline-start" aria-label={restoreLabel} />
          ) : (
            <RotateCcw data-icon="inline-start" />
          )}
          {restoreLabel}
        </Button>
        <Button
          type="button"
          variant="destructive"
          size="sm"
          disabled={disabled}
          onClick={onDelete}
        >
          <Trash2 data-icon="inline-start" />
          {deleteLabel}
        </Button>
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
  templatePreviewResume,
  onRestoreResume,
  onDeleteResumeForever,
  onRestoreTemplate,
  onDeleteTemplateForever,
}: {
  locale: Locale;
  t: AppMessages;
  deletedResumes: DeletedResumeWorkspaceItem[];
  deletedTemplates: DeletedResumeTemplateDefinition[];
  templates: ResumeTemplateDefinition[];
  templatePreviewResume: ResumeData;
  onRestoreResume: (resumeIds: string[]) => Promise<boolean>;
  onDeleteResumeForever: (resumeIds: string[]) => Promise<boolean>;
  onRestoreTemplate: (templateIds: string[]) => Promise<boolean>;
  onDeleteTemplateForever: (templateIds: string[]) => Promise<boolean>;
}) {
  const [searchParams, setSearchParams] = useSearchParams();
  const activeTab: RecycleBinTab =
    searchParams.get("tab") === "templates" ? "templates" : "resumes";
  const pageSearchParam = searchParams.get("page");
  const requestedPage = Number(pageSearchParam);
  const hasValidRequestedPage =
    Number.isSafeInteger(requestedPage) && requestedPage > 0;
  const currentPage =
    hasValidRequestedPage ? requestedPage : 1;
  const [pendingAction, setPendingAction] = useState<PendingTrashAction>(null);
  const [runningActionKey, setRunningActionKey] =
    useState<TrashActionKey | null>(null);
  const [selectedResumeIds, setSelectedResumeIds] = useState<string[]>([]);
  const [selectedTemplateIds, setSelectedTemplateIds] = useState<string[]>([]);
  // State drives feedback; the ref closes the same-render double-click gap.
  const runningActionRef = useRef<TrashActionKey | null>(null);

  const isDialogOpen = Boolean(pendingAction);
  const previewTemplates = [...templates, ...deletedTemplates];
  const deletedResumeIdSet = useMemo(
    () => new Set(deletedResumes.map((item) => item.id)),
    [deletedResumes],
  );
  const deletedTemplateIdSet = useMemo(
    () => new Set(deletedTemplates.map((item) => item.id)),
    [deletedTemplates],
  );
  const resumeTotalPages = Math.max(
    1,
    Math.ceil(deletedResumes.length / TRASH_PAGE_SIZE),
  );
  const templateTotalPages = Math.max(
    1,
    Math.ceil(deletedTemplates.length / TRASH_PAGE_SIZE),
  );
  const activeTotalPages =
    activeTab === "resumes" ? resumeTotalPages : templateTotalPages;
  const safeCurrentPage = Math.min(currentPage, activeTotalPages);
  const pageStart = (safeCurrentPage - 1) * TRASH_PAGE_SIZE;
  const paginatedDeletedResumes =
    activeTab === "resumes"
      ? deletedResumes.slice(pageStart, pageStart + TRASH_PAGE_SIZE)
      : [];
  const paginatedDeletedTemplates =
    activeTab === "templates"
      ? deletedTemplates.slice(pageStart, pageStart + TRASH_PAGE_SIZE)
      : [];
  const currentResumePageIdSet = new Set(
    paginatedDeletedResumes.map((item) => item.id),
  );
  const currentTemplatePageIdSet = new Set(
    paginatedDeletedTemplates.map((item) => item.id),
  );
  const validSelectedResumeIds = selectedResumeIds.filter((id) =>
    deletedResumeIdSet.has(id),
  );
  const validSelectedTemplateIds = selectedTemplateIds.filter((id) =>
    deletedTemplateIdSet.has(id),
  );
  const selectedResumePageIds = validSelectedResumeIds.filter((id) =>
    currentResumePageIdSet.has(id),
  );
  const selectedTemplatePageIds = validSelectedTemplateIds.filter((id) =>
    currentTemplatePageIdSet.has(id),
  );
  const selectedResumeIdSet = new Set(validSelectedResumeIds);
  const selectedTemplateIdSet = new Set(validSelectedTemplateIds);
  const activeSelectedIds =
    activeTab === "resumes"
      ? selectedResumePageIds
      : selectedTemplatePageIds;

  // A restore, permanent delete, or external refresh can remove rows while a
  // selection is active. Keep selection state limited to rows still rendered.
  useEffect(() => {
    setSelectedResumeIds((current) =>
      current.filter((id) => deletedResumeIdSet.has(id)),
    );
  }, [deletedResumeIdSet]);

  useEffect(() => {
    setSelectedTemplateIds((current) =>
      current.filter((id) => deletedTemplateIdSet.has(id)),
    );
  }, [deletedTemplateIdSet]);

  useEffect(() => {
    const needsPageCorrection =
      (pageSearchParam !== null && !hasValidRequestedPage) ||
      currentPage !== safeCurrentPage;

    if (!needsPageCorrection) {
      return;
    }

    // Restoring or deleting the last row can remove the current page. Keep the
    // URL and selection aligned with the page that is actually rendered.
    if (activeTab === "resumes") {
      setSelectedResumeIds([]);
    } else {
      setSelectedTemplateIds([]);
    }

    setSearchParams(
      (current) => {
        const next = new URLSearchParams(current);

        if (safeCurrentPage > 1) {
          next.set("page", String(safeCurrentPage));
        } else {
          next.delete("page");
        }

        return next;
      },
      { replace: true },
    );
  }, [
    activeTab,
    currentPage,
    hasValidRequestedPage,
    pageSearchParam,
    safeCurrentPage,
    setSearchParams,
  ]);

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
    }

    if (succeeded) {
      if (pendingAction.type === "resume-item") {
        const deletedIdSet = new Set(pendingAction.ids);
        setSelectedResumeIds((current) =>
          current.filter((id) => !deletedIdSet.has(id)),
        );
      } else if (pendingAction.type === "template-item") {
        const deletedIdSet = new Set(pendingAction.ids);
        setSelectedTemplateIds((current) =>
          current.filter((id) => !deletedIdSet.has(id)),
        );
      }

      closeDialog();
    }
  }

  async function restoreResumeIds(ids: string[], key: TrashActionKey) {
    const succeeded = await runTrashAction(key, () => onRestoreResume(ids));

    if (succeeded) {
      const restoredIdSet = new Set(ids);
      setSelectedResumeIds((current) =>
        current.filter((id) => !restoredIdSet.has(id)),
      );
    }
  }

  async function restoreTemplateIds(ids: string[], key: TrashActionKey) {
    const succeeded = await runTrashAction(key, () => onRestoreTemplate(ids));

    if (succeeded) {
      const restoredIdSet = new Set(ids);
      setSelectedTemplateIds((current) =>
        current.filter((id) => !restoredIdSet.has(id)),
      );
    }
  }

  function selectAllActiveItems(selected: boolean) {
    if (activeTab === "resumes") {
      setSelectedResumeIds(
        selected ? paginatedDeletedResumes.map((item) => item.id) : [],
      );
      return;
    }

    setSelectedTemplateIds(
      selected ? paginatedDeletedTemplates.map((item) => item.id) : [],
    );
  }

  function changePage(page: number) {
    if (
      runningActionRef.current ||
      page === safeCurrentPage ||
      page < 1 ||
      page > activeTotalPages
    ) {
      return;
    }

    if (activeTab === "resumes") {
      setSelectedResumeIds([]);
    } else {
      setSelectedTemplateIds([]);
    }

    setSearchParams((current) => {
      const next = new URLSearchParams(current);

      if (page > 1) {
        next.set("page", String(page));
      } else {
        next.delete("page");
      }

      return next;
    });
  }

  function restoreSelectedActiveItems() {
    if (activeSelectedIds.length === 0) {
      return;
    }

    if (activeTab === "resumes") {
      void restoreResumeIds(
        [...activeSelectedIds],
        "resume-restore-selected",
      );
      return;
    }

    void restoreTemplateIds(
      [...activeSelectedIds],
      "template-restore-selected",
    );
  }

  function deleteSelectedActiveItems() {
    if (activeSelectedIds.length === 0) {
      return;
    }

    setPendingAction(
      activeTab === "resumes"
        ? { type: "resume-item", ids: [...activeSelectedIds] }
        : { type: "template-item", ids: [...activeSelectedIds] },
    );
  }

  const dialogTitle =
    pendingAction?.type === "resume-item"
      ? pendingAction.ids.length > 1
        ? t.confirmDeleteResumesForeverTitle
        : t.confirmDeleteResumeForeverTitle
      : pendingAction?.type === "template-item"
        ? pendingAction.ids.length > 1
          ? t.confirmDeleteTemplatesForeverTitle
          : t.confirmDeleteTemplateForeverTitle
        : "";

  const dialogDescription =
    pendingAction?.type === "resume-item"
      ? pendingAction.ids.length > 1
        ? t.confirmDeleteResumesForeverDescription
        : t.confirmDeleteResumeForeverDescription
      : pendingAction?.type === "template-item"
        ? pendingAction.ids.length > 1
          ? t.confirmDeleteTemplatesForeverDescription
          : t.confirmDeleteTemplateForeverDescription
        : "";

  const dialogActionLabel =
    (pendingAction?.ids.length ?? 0) > 1
      ? t.deleteSelectedForever
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

              next.delete("page");
              return next;
            });
          }}
          className="gap-0"
        >
          <div className="flex flex-wrap items-center gap-3 border-b border-border/70">
            <TabsList
              variant="line"
              className="w-fit justify-start gap-8 p-0 group-data-[orientation=horizontal]/tabs:h-9"
            >
              <TabsTrigger
                value="resumes"
                disabled={runningActionKey !== null}
                className="h-9 min-w-0 flex-none rounded-none border-transparent px-0 py-0 text-sm font-semibold after:bottom-[-1px]!"
              >
                {t.resumeRecycleBin}
                <CountBadge count={deletedResumes.length} />
              </TabsTrigger>
              <TabsTrigger
                value="templates"
                disabled={runningActionKey !== null}
                className="h-9 min-w-0 flex-none rounded-none border-transparent px-0 py-0 text-sm font-semibold after:bottom-[-1px]!"
              >
                {t.templateRecycleBin}
                <CountBadge count={deletedTemplates.length} />
              </TabsTrigger>
            </TabsList>
          </div>

          <TabsContent value="resumes" className="mt-0">
            <div className="overflow-hidden">
              {deletedResumes.length > 0 ? (
                <>
                  <TrashSelectionToolbar
                    selectionId="select-all-deleted-resumes"
                    selectAllLabel={t.selectAll}
                    restoreLabel={t.restoreSelected}
                    deleteLabel={t.deleteSelectedForever}
                    selectedCount={selectedResumePageIds.length}
                    itemCount={paginatedDeletedResumes.length}
                    onSelectAll={selectAllActiveItems}
                    onRestore={restoreSelectedActiveItems}
                    onDelete={deleteSelectedActiveItems}
                    isRestoring={
                      runningActionKey === "resume-restore-selected"
                    }
                    disabled={runningActionKey !== null}
                  />

                  {paginatedDeletedResumes.map((item) => {
                    const title =
                      item.title || item.resume.basic.name || t.untitledResume;
                    const deletedAt = formatAt(locale, item.deletedAt);
                    const template = getTemplateById(
                      previewTemplates,
                      item.template,
                    );
                    const restoreActionKey =
                      `resume-restore:${item.id}` as const;

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
                          deletedAtText={`${t.recycleBinDeletedAtPrefix} ${deletedAt}`}
                          restoreLabel={t.restore}
                          deleteLabel={t.deleteForever}
                          isRestoring={runningActionKey === restoreActionKey}
                          disabled={runningActionKey !== null}
                          selected={selectedResumeIdSet.has(item.id)}
                          selectLabel={t.selectItems}
                          onSelectedChange={(selected) => {
                            setSelectedResumeIds((current) =>
                              selected
                                ? current.includes(item.id)
                                  ? current
                                  : [...current, item.id]
                                : current.filter((id) => id !== item.id),
                            );
                          }}
                          onRestore={() => {
                            void restoreResumeIds(
                              [item.id],
                              restoreActionKey,
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
                  })}
                  <GalleryPagination
                    currentPage={safeCurrentPage}
                    totalPages={resumeTotalPages}
                    t={t}
                    onPageChange={changePage}
                    disabled={runningActionKey !== null}
                  />
                </>
              ) : (
                <EmptyTrashState>{t.emptyResumeTrash}</EmptyTrashState>
              )}
            </div>
          </TabsContent>

          <TabsContent value="templates" className="mt-0">
            <div className="overflow-hidden">
              {deletedTemplates.length > 0 ? (
                <>
                  <TrashSelectionToolbar
                    selectionId="select-all-deleted-templates"
                    selectAllLabel={t.selectAll}
                    restoreLabel={t.restoreSelected}
                    deleteLabel={t.deleteSelectedForever}
                    selectedCount={selectedTemplatePageIds.length}
                    itemCount={paginatedDeletedTemplates.length}
                    onSelectAll={selectAllActiveItems}
                    onRestore={restoreSelectedActiveItems}
                    onDelete={deleteSelectedActiveItems}
                    isRestoring={
                      runningActionKey === "template-restore-selected"
                    }
                    disabled={runningActionKey !== null}
                  />

                  {paginatedDeletedTemplates.map((item) => {
                    const deletedAt = formatAt(locale, item.deletedAt);
                    const restoreActionKey =
                      `template-restore:${item.id}` as const;

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
                              showEmptyTemplateImagePlaceholders
                            />
                          }
                          title={item.name}
                          subtitle={
                            item.description || t.templateDescriptionFallback
                          }
                          deletedAtText={`${t.recycleBinDeletedAtPrefix} ${deletedAt}`}
                          restoreLabel={t.restore}
                          deleteLabel={t.deleteForever}
                          isRestoring={runningActionKey === restoreActionKey}
                          disabled={runningActionKey !== null}
                          selected={selectedTemplateIdSet.has(item.id)}
                          selectLabel={t.selectItems}
                          onSelectedChange={(selected) => {
                            setSelectedTemplateIds((current) =>
                              selected
                                ? current.includes(item.id)
                                  ? current
                                  : [...current, item.id]
                                : current.filter((id) => id !== item.id),
                            );
                          }}
                          onRestore={() => {
                            void restoreTemplateIds(
                              [item.id],
                              restoreActionKey,
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
                  })}
                  <GalleryPagination
                    currentPage={safeCurrentPage}
                    totalPages={templateTotalPages}
                    t={t}
                    onPageChange={changePage}
                    disabled={runningActionKey !== null}
                  />
                </>
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
