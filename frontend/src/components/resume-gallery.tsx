import { Check, Clock3, FileUp, PlusSquare, Trash2 } from "lucide-react";
import {
  useDeferredValue,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
} from "react";
import { Link } from "react-router-dom";

import type { AppMessages, Locale } from "@/i18n";
import { getTemplateById } from "@/lib/templates";
import { cn } from "@/lib/utils";
import type {
  ResumeTemplateDefinition,
  ResumeWorkspaceItem,
} from "@/types/resume";

import { ConfirmActionDialog } from "@/components/confirm-action-dialog";
import { GalleryPagination } from "@/components/gallery-pagination";
import { GalleryToolbar } from "@/components/gallery-toolbar";
import { ResumePreview } from "@/components/preview/resume-preview";
import { Button } from "@/components/ui/button";
import { Empty, EmptyDescription } from "@/components/ui/empty";
import { Spinner } from "@/components/ui/spinner";
import { ViewTransitionBoundary } from "@/components/view-transition";
import { useGalleryGridPageSize } from "@/components/use-gallery-grid-page-size";
import { useGalleryUrlState } from "@/components/use-gallery-url-state";

function matchesResumeQuery(
  query: string,
  item: Pick<ResumeWorkspaceItem, "resume" | "title">,
) {
  if (!query) {
    return true;
  }

  return [
    item.title,
    item.resume.basic.name,
    item.resume.basic.headline,
    item.resume.basic.email,
    item.resume.basic.phone,
  ]
    .join(" ")
    .toLowerCase()
    .includes(query);
}

function createUpdatedAtFormatter(locale: Locale) {
  return new Intl.DateTimeFormat(locale === "zh" ? "zh-CN" : "en-US", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function ResumeGallery({
  locale,
  t,
  resumes,
  templates,
  defaultTemplateId,
  isImporting,
  isCreating,
  onOpenResume,
  onCreateResume,
  onImportResume,
  onDeleteResume,
  onBulkDeleteResumes,
}: {
  locale: Locale;
  t: AppMessages;
  resumes: ResumeWorkspaceItem[];
  templates: ResumeTemplateDefinition[];
  defaultTemplateId: string;
  isImporting: boolean;
  isCreating: boolean;
  onOpenResume: (resumeId: string) => void;
  onCreateResume: () => void;
  onImportResume: (file: File) => void;
  onDeleteResume: (resumeId: string) => void;
  onBulkDeleteResumes: (resumeIds: string[]) => void;
}) {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [isSelecting, setIsSelecting] = useState(false);
  const [pendingDeleteIds, setPendingDeleteIds] = useState<string[]>([]);
  const [isDeleteDialogOpen, setIsDeleteDialogOpen] = useState(false);
  const { currentPage, searchQuery, setCurrentPage, setSearchQuery } =
    useGalleryUrlState();
  const { gridRef, pageSize } = useGalleryGridPageSize({ fixedItems: 0 });
  const deferredSearchQuery = useDeferredValue(searchQuery);

  function handleImportChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];

    if (!file) {
      return;
    }

    onImportResume(file);
    event.target.value = "";
  }

  function toggleSelected(resumeId: string) {
    setSelectedIds((current) =>
      current.includes(resumeId)
        ? current.filter((id) => id !== resumeId)
        : [...current, resumeId],
    );
  }

  function toggleSelecting() {
    setIsSelecting((current) => {
      if (current) {
        setSelectedIds([]);
      }

      return !current;
    });
  }

  function requestDelete(resumeIds: string[]) {
    if (resumeIds.length === 0) {
      return;
    }

    setPendingDeleteIds(resumeIds);
    setIsDeleteDialogOpen(true);
  }

  function confirmDelete() {
    if (pendingDeleteIds.length === 1) {
      onDeleteResume(pendingDeleteIds[0]);
    } else if (pendingDeleteIds.length > 1) {
      const pendingDeleteIdSet = new Set(pendingDeleteIds);

      onBulkDeleteResumes(pendingDeleteIds);
      setSelectedIds((current) =>
        current.filter((id) => !pendingDeleteIdSet.has(id)),
      );
    }

    setPendingDeleteIds([]);
    setIsDeleteDialogOpen(false);
  }

  const normalizedQuery = deferredSearchQuery.trim().toLowerCase();
  const resumeIdSet = useMemo(
    () => new Set(resumes.map((item) => item.id)),
    [resumes],
  );
  const selectedIdSet = useMemo(() => new Set(selectedIds), [selectedIds]);
  const selectedResumeIds = useMemo(
    () => selectedIds.filter((id) => resumeIdSet.has(id)),
    [resumeIdSet, selectedIds],
  );
  const visibleResumes = useMemo(
    () =>
      resumes.filter((item) => matchesResumeQuery(normalizedQuery, item)),
    [normalizedQuery, resumes],
  );
  const updatedAtFormatter = useMemo(
    () => createUpdatedAtFormatter(locale),
    [locale],
  );
  const totalPages = Math.max(
    1,
    Math.ceil(visibleResumes.length / pageSize),
  );
  const safeCurrentPage = Math.min(currentPage, totalPages);
  const paginatedResumes = visibleResumes.slice(
    (safeCurrentPage - 1) * pageSize,
    safeCurrentPage * pageSize,
  );

  return (
    <section className="rounded-(--radius-workspace) border border-border bg-muted/35 p-3.5 text-foreground sm:p-4">
      <ConfirmActionDialog
        open={isDeleteDialogOpen}
        title={
          pendingDeleteIds.length > 1
            ? t.confirmDeleteResumesTitle
            : t.confirmDeleteResumeTitle
        }
        description={
          pendingDeleteIds.length > 1
            ? t.confirmDeleteResumesDescription
            : t.confirmDeleteResumeDescription
        }
        confirmLabel={t.confirmDeleteAction}
        cancelLabel={t.cancel}
        onConfirm={confirmDelete}
        onOpenChange={(open) => {
          setIsDeleteDialogOpen(open);
          if (!open) {
            setPendingDeleteIds([]);
          }
        }}
      />

      <input
        ref={fileInputRef}
        type="file"
        accept=".pdf,application/pdf,.json,application/json"
        className="hidden"
        disabled={isImporting}
        onChange={handleImportChange}
      />

      <GalleryToolbar
        searchLabel={t.searchResumesLabel}
        searchName="resume-search"
        searchPlaceholder={t.searchResumesPlaceholder}
        searchValue={searchQuery}
        onSearchChange={(value) => {
          setSearchQuery(value);
        }}
        isSelecting={isSelecting}
        onToggleSelecting={toggleSelecting}
        selectedCount={selectedResumeIds.length}
        selectLabel={t.selectItems}
        cancelLabel={t.cancelSelection}
        bulkDeleteLabel={t.bulkDelete}
        onBulkDelete={() => requestDelete(selectedResumeIds)}
        leadingActions={
          <>
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
              {isImporting ? t.importing : t.importResume}
            </Button>
            <Button
              type="button"
              disabled={isImporting || isCreating}
              onClick={onCreateResume}
            >
              {isCreating ? (
                <Spinner data-icon="inline-start" aria-label={t.newResume} />
              ) : (
                <PlusSquare data-icon="inline-start" />
              )}
              {t.newResume}
            </Button>
          </>
        }
      />

      <div
        ref={gridRef}
        className="grid auto-rows-fr grid-cols-[repeat(auto-fit,minmax(208px,228px))] gap-4"
      >
        {paginatedResumes.length === 0 ? (
          <Empty className="col-span-full min-h-[390px] border border-border/70 bg-card/55">
            <EmptyDescription className="font-medium">
              {resumes.length === 0 ? t.emptyResumes : t.emptyResumeSearch}
            </EmptyDescription>
          </Empty>
        ) : null}

        {paginatedResumes.map((item) => {
          const template = getTemplateById(
            templates,
            item.template,
            defaultTemplateId,
          );
          const isSelected = selectedIdSet.has(item.id);
          const resumeLabel =
            item.title || item.resume.basic.name || t.untitledResume;

          return (
            <ViewTransitionBoundary
              key={item.id}
              enter="fade-in"
              exit="fade-out"
              default="none"
            >
              <div className="group relative h-full">
                <Link
                  to={`/resume/${item.id}`}
                  role={isSelecting ? "button" : undefined}
                  aria-label={resumeLabel}
                  aria-pressed={isSelecting ? isSelected : undefined}
                  className="block h-full rounded-(--radius-card) text-left outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                  onClick={(event) => {
                    if (isSelecting) {
                      event.preventDefault();
                      toggleSelected(item.id);
                      return;
                    }

                    if (
                      event.button === 0 &&
                      !event.metaKey &&
                      !event.ctrlKey &&
                      !event.shiftKey &&
                      !event.altKey
                    ) {
                      event.preventDefault();
                      onOpenResume(item.id);
                    }
                  }}
                  onKeyDown={(event) => {
                    if (isSelecting && event.key === " ") {
                      event.preventDefault();
                      toggleSelected(item.id);
                    }
                  }}
                >
                  <div
                    className={cn(
                      "flex h-full flex-col rounded-(--radius-card) border border-border/80 bg-card p-2.5 shadow-none transition-colors duration-200 group-hover:border-border group-hover:bg-accent/20",
                      isSelected && "border-primary bg-accent/20",
                    )}
                  >
                    <div className="rounded-[18px] bg-muted/55 p-2">
                      <ViewTransitionBoundary
                        name={`resume-preview-${item.id}`}
                        share="morph"
                        default="none"
                      >
                        <div className="relative mx-auto h-[258px] w-[182px] overflow-hidden rounded-[14px] border border-zinc-200 bg-white">
                          {isSelecting ? (
                            <span
                              aria-hidden="true"
                              className={cn(
                                "absolute left-3 top-3 z-10 flex size-7 items-center justify-center rounded-full border backdrop-blur",
                                isSelected
                                  ? "border-primary bg-primary text-primary-foreground"
                                  : "border-border/80 bg-background/92 text-muted-foreground",
                              )}
                            >
                              <Check className="size-3.5" />
                            </span>
                          ) : null}

                          <div
                            aria-hidden="true"
                            className="pointer-events-none absolute left-0 top-0 origin-top-left scale-[0.224]"
                            style={{ width: "210mm", height: "297mm" }}
                          >
                            <ResumePreview
                              t={t}
                              resume={item.resume}
                              fontFamily={item.typography?.fontFamily ?? "inter"}
                              fontSize={item.typography?.fontSize ?? 15}
                              template={template}
                              variant="thumbnail"
                            />
                          </div>
                        </div>
                      </ViewTransitionBoundary>
                    </div>

                    <div className="flex min-h-[92px] flex-1 flex-col justify-between px-1 pt-3">
                      <div>
                        <p
                          className="truncate text-[15px] font-semibold"
                          title={resumeLabel}
                        >
                          {resumeLabel}
                        </p>
                        <p className="mt-1 truncate text-xs text-muted-foreground">
                          {item.resume.basic.headline ||
                            item.resume.basic.email ||
                            item.resume.basic.phone}
                        </p>
                      </div>

                      <p className="mt-2 inline-flex items-center gap-1.5 text-[11px] text-muted-foreground">
                        <Clock3 className="size-3" />
                        {updatedAtFormatter.format(new Date(item.updatedAt))}
                      </p>
                    </div>
                  </div>
                </Link>
                {isSelecting && isSelected ? (
                  <Button
                    type="button"
                    variant="destructive"
                    size="icon-sm"
                    aria-label={t.confirmDeleteAction}
                    className="absolute right-8 top-8 z-10 size-7 rounded-full backdrop-blur"
                    onClick={() => requestDelete([item.id])}
                  >
                    <Trash2 className="size-3.5" />
                  </Button>
                ) : null}
              </div>
            </ViewTransitionBoundary>
          );
        })}
      </div>

      <GalleryPagination
        currentPage={safeCurrentPage}
        totalPages={totalPages}
        t={t}
        onPageChange={setCurrentPage}
      />
    </section>
  );
}
