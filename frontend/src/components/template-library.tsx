import {
  Check,
  ChevronDown,
  CopyPlus,
  FileUp,
  ImagePlus,
  Plus,
  Sparkles,
  Trash2,
} from "lucide-react";
import {
  useDeferredValue,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type ReactNode,
} from "react";

import type { AppMessages, Locale } from "@/i18n";
import { readAvatarFileAsDataUrl } from "@/lib/avatar";
import { createId, getSectionTitle } from "@/lib/resume";
import { cn } from "@/lib/utils";
import type {
  ResumeAvatarPosition,
  ResumeAvatarShape,
  ResumeBasicInfoLayout,
  ResumeData,
  ResumeFontFamily,
  ResumeSectionTemplateStyle,
  ResumeTemplateDefinition,
  ResumeTemplateImageElement,
  ResumeTemplateImageFit,
  ResumeTemplateLayout,
  ResumeTemplateSettings,
  SectionKind,
} from "@/types/resume";

import { ConfirmActionDialog } from "@/components/confirm-action-dialog";
import { GalleryPagination } from "@/components/gallery-pagination";
import { GalleryToolbar } from "@/components/gallery-toolbar";
import { ResumePreview } from "@/components/preview/resume-preview";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { ViewTransitionBoundary } from "@/components/ui/view-transition";
import { useGalleryGridPageSize } from "@/components/use-gallery-grid-page-size";

const fontSizeOptions = [12, 14, 16, 18, 20] as const;
const previewSectionKinds: SectionKind[] = [
  "education",
  "work",
  "internship",
  "project",
  "skills",
  "awards",
  "certificates",
  "languages",
  "other",
  "custom",
];

type TemplateEditorTab = "layout" | "typography" | "visual" | "images";

function TemplateEditorPanel({
  title,
  description,
  badge,
  defaultOpen = true,
  children,
}: {
  title: string;
  description?: string;
  badge?: ReactNode;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  return (
    <Collapsible
      defaultOpen={defaultOpen}
      className="rounded-[24px] bg-muted/20 ring-1 ring-border/25"
    >
      <CollapsibleTrigger className="group flex w-full cursor-pointer items-center justify-between gap-3 px-4 py-3 text-left">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-sm font-semibold tracking-[-0.02em] text-foreground">
              {title}
            </p>
            {badge}
          </div>
          {description ? (
            <p className="mt-0.5 text-[11px] leading-5 text-muted-foreground">
              {description}
            </p>
          ) : null}
        </div>
        <ChevronDown className="size-4 shrink-0 text-muted-foreground transition-transform duration-200 group-data-[state=open]:rotate-180" />
      </CollapsibleTrigger>
      <CollapsibleContent className="collapsible-content px-4 pb-4">
        {children}
      </CollapsibleContent>
    </Collapsible>
  );
}

function TemplateSliderField({
  label,
  min,
  max,
  step,
  value,
  displayValue,
  onChange,
  disabled = false,
}: {
  label: string;
  min: number;
  max: number;
  step: number;
  value: number;
  displayValue: string;
  onChange: (value: number) => void;
  disabled?: boolean;
}) {
  return (
    <div
      className={cn(
        "grid gap-2 rounded-[18px] bg-muted/35 p-3 shadow-[inset_0_1px_0_rgba(255,255,255,0.55)]",
        disabled && "opacity-70",
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-medium">{label}</span>
        <span className="text-xs text-muted-foreground">{displayValue}</span>
      </div>
      <Slider
        min={min}
        max={max}
        step={step}
        value={[value]}
        onValueChange={(next) => onChange(next[0] ?? value)}
        disabled={disabled}
      />
    </div>
  );
}

function TemplateColorField({
  label,
  value,
  onChange,
  disabled = false,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  return (
    <div
      className={cn(
        "grid gap-2 rounded-[18px] bg-muted/35 p-3 shadow-[inset_0_1px_0_rgba(255,255,255,0.55)]",
        disabled && "opacity-70",
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-medium">{label}</span>
        <span className="rounded-md border border-border/70 bg-background px-2 py-1 font-mono text-[11px] uppercase tracking-[0.08em] text-muted-foreground">
          {value}
        </span>
      </div>
      <div className="flex items-center gap-3">
        <Input
          type="color"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          className="h-10 w-14 shrink-0 cursor-pointer rounded-lg border border-border/70 bg-background p-1"
          disabled={disabled}
        />
        <div
          className="h-10 flex-1 rounded-lg border border-border/70 bg-background"
          style={{ backgroundColor: value }}
        />
      </div>
    </div>
  );
}

function getScaleLabel(baseFontSize: number, value: number) {
  return `~${Math.round(baseFontSize * value)}px`;
}

function matchesTemplateQuery(
  query: string,
  item: Pick<ResumeTemplateDefinition, "name" | "description">,
) {
  if (!query) {
    return true;
  }

  return `${item.name} ${item.description}`.toLowerCase().includes(query);
}

function createTemplateImageElement(
  index: number,
  layout?: ResumeTemplateLayout,
): ResumeTemplateImageElement {
  const placeOnLeft = layout?.avatarPosition === "right";

  return {
    id: createId("image"),
    name: `Image ${index}`,
    src: "",
    alt: "",
    x: placeOnLeft ? 14 : 166,
    y: 18,
    width: 30,
    height: 20,
    opacity: 1,
    borderWidth: 0.8,
    borderColor: "#d4d4d8",
    borderRadius: 8,
    objectFit: "contain",
    visible: true,
  };
}

export function TemplateLibrary({
  mode,
  locale,
  t,
  resume,
  templates,
  defaultTemplateId,
  activeTemplateId,
  onOpenTemplate,
  onSetDefaultTemplate,
  onCreateCustomTemplate,
  onImportTemplates,
  onUpdateTemplate,
  onDeleteTemplate,
  onBulkDeleteTemplates,
  onAddPreviewSection,
  onRemovePreviewSection,
}: {
  mode: "gallery" | "editor";
  locale: Locale;
  t: AppMessages;
  resume: ResumeData;
  templates: ResumeTemplateDefinition[];
  defaultTemplateId: string;
  activeTemplateId: string;
  onOpenTemplate: (templateId: string) => void;
  onSetDefaultTemplate: (templateId: string) => void;
  onCreateCustomTemplate: () => void;
  onImportTemplates: (file: File) => void;
  onUpdateTemplate: (
    templateId: string,
    patch: Partial<ResumeTemplateDefinition>,
  ) => void;
  onDeleteTemplate: (templateId: string) => void;
  onBulkDeleteTemplates: (templateIds: string[]) => void;
  onAddPreviewSection?: (kind: SectionKind) => void;
  onRemovePreviewSection?: (sectionId: string) => void;
}) {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [isSelecting, setIsSelecting] = useState(false);
  const [pendingDeleteIds, setPendingDeleteIds] = useState<string[]>([]);
  const [isDeleteDialogOpen, setIsDeleteDialogOpen] = useState(false);
  const [editorTab, setEditorTab] = useState<TemplateEditorTab>("layout");
  const [currentPage, setCurrentPage] = useState(1);
  const { gridRef, pageSize } = useGalleryGridPageSize({ fixedItems: 1 });
  const deferredSearchQuery = useDeferredValue(searchQuery);
  const activeTemplate = useMemo(
    () => templates.find((item) => item.id === activeTemplateId) ?? templates[0],
    [activeTemplateId, templates],
  );
  const isTemplateReadonly = Boolean(activeTemplate?.isBuiltIn);
  const customTemplateIdSet = useMemo(
    () => new Set(templates.filter((item) => !item.isBuiltIn).map((item) => item.id)),
    [templates],
  );
  const selectedIdSet = useMemo(() => new Set(selectedIds), [selectedIds]);
  const selectedTemplateIds = useMemo(
    () => selectedIds.filter((id) => customTemplateIdSet.has(id)),
    [customTemplateIdSet, selectedIds],
  );
  const normalizedQuery = deferredSearchQuery.trim().toLowerCase();
  const visibleTemplates = useMemo(
    () =>
      templates.filter((item) => matchesTemplateQuery(normalizedQuery, item)),
    [normalizedQuery, templates],
  );
  const totalPages = Math.max(
    1,
    Math.ceil(visibleTemplates.length / pageSize),
  );
  const safeCurrentPage = Math.min(currentPage, totalPages);
  const paginatedTemplates = visibleTemplates.slice(
    (safeCurrentPage - 1) * pageSize,
    safeCurrentPage * pageSize,
  );
  const previewModuleCount = resume.sections.length + 1;

  function handleImportChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];

    if (!file) {
      return;
    }

    onImportTemplates(file);
    event.target.value = "";
  }

  function toggleSelected(templateId: string) {
    setSelectedIds((current) =>
      current.includes(templateId)
        ? current.filter((id) => id !== templateId)
        : [...current, templateId],
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

  function requestDelete(templateIds: string[]) {
    const customTemplateIds = templateIds.filter((id) =>
      customTemplateIdSet.has(id),
    );

    if (customTemplateIds.length === 0) {
      return;
    }

    setPendingDeleteIds(customTemplateIds);
    setIsDeleteDialogOpen(true);
  }

  function confirmDelete() {
    if (pendingDeleteIds.length === 1) {
      onDeleteTemplate(pendingDeleteIds[0]);
    } else if (pendingDeleteIds.length > 1) {
      const pendingDeleteIdSet = new Set(pendingDeleteIds);

      onBulkDeleteTemplates(pendingDeleteIds);
      setSelectedIds((current) =>
        current.filter((id) => !pendingDeleteIdSet.has(id)),
      );
    }

    setPendingDeleteIds([]);
    setIsDeleteDialogOpen(false);
  }

  function updateSettings(patch: Partial<ResumeTemplateSettings>) {
    if (!activeTemplate || activeTemplate.isBuiltIn) {
      return;
    }

    onUpdateTemplate(activeTemplate.id, {
      settings: {
        ...activeTemplate.settings,
        ...patch,
      },
    });
  }

  function updateLayout(patch: Partial<ResumeTemplateLayout>) {
    if (!activeTemplate || activeTemplate.isBuiltIn) {
      return;
    }

    onUpdateTemplate(activeTemplate.id, {
      layout: {
        ...activeTemplate.layout,
        ...patch,
      },
    });
  }

  function addTemplateImage() {
    if (!activeTemplate || activeTemplate.isBuiltIn) {
      return;
    }

    updateLayout({
      images: [
        ...(activeTemplate.layout.images ?? []),
        createTemplateImageElement(
          (activeTemplate.layout.images ?? []).length + 1,
          activeTemplate.layout,
        ),
      ],
    });
  }

  function updateTemplateImage(
    imageId: string,
    patch: Partial<ResumeTemplateImageElement>,
  ) {
    if (!activeTemplate || activeTemplate.isBuiltIn) {
      return;
    }

    updateLayout({
      images: (activeTemplate.layout.images ?? []).map((image) =>
        image.id === imageId ? { ...image, ...patch } : image,
      ),
    });
  }

  function removeTemplateImage(imageId: string) {
    if (!activeTemplate || activeTemplate.isBuiltIn) {
      return;
    }

    updateLayout({
      images: (activeTemplate.layout.images ?? []).filter((image) => image.id !== imageId),
    });
  }

  async function handleTemplateImageUpload(
    imageId: string,
    file: File | undefined,
  ) {
    if (!file) {
      return;
    }

    try {
      const src = await readAvatarFileAsDataUrl(file);
      updateTemplateImage(imageId, {
        src,
        alt: file.name,
        name: file.name.replace(/\.[^.]+$/, "") || file.name,
      });
    } catch (error) {
      console.error("Failed to import template image.", error);
    }
  }

  function handleTemplateCardAction(item: ResumeTemplateDefinition) {
    if (isSelecting) {
      toggleSelected(item.id);
      return;
    }

    onOpenTemplate(item.id);
  }

  if (mode === "gallery") {
    return (
      <section className="rounded-[26px] border border-border bg-muted/35 p-3.5 text-foreground sm:p-4">
        <ConfirmActionDialog
          open={isDeleteDialogOpen}
          title={
            pendingDeleteIds.length > 1
              ? t.confirmDeleteTemplatesTitle
              : t.confirmDeleteTemplateTitle
          }
          description={
            pendingDeleteIds.length > 1
              ? t.confirmDeleteTemplatesDescription
              : t.confirmDeleteTemplateDescription
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
          accept=".json,application/json"
          className="hidden"
          onChange={handleImportChange}
        />

        <GalleryToolbar
          searchPlaceholder={t.searchTemplatesPlaceholder}
          searchValue={searchQuery}
          onSearchChange={(value) => {
            setSearchQuery(value);
            setCurrentPage(1);
          }}
          isSelecting={isSelecting}
          onToggleSelecting={toggleSelecting}
          selectedCount={selectedTemplateIds.length}
          selectLabel={t.selectItems}
          cancelLabel={t.cancelSelection}
          bulkDeleteLabel={t.bulkDelete}
          onBulkDelete={() => requestDelete(selectedTemplateIds)}
        />

        <div
          ref={gridRef}
          className="grid auto-rows-fr grid-cols-[repeat(auto-fit,minmax(208px,228px))] gap-4"
        >
          <Card className="h-full rounded-[24px] border-border/80 bg-card text-card-foreground shadow-none">
            <CardContent className="flex h-full flex-col p-2.5">
              <div className="rounded-[18px] bg-muted/55 p-2">
                <div className="flex h-[258px] items-center justify-center rounded-[14px] border border-dashed border-border bg-background">
                  <div className="text-center">
                    <div className="mx-auto flex size-12 items-center justify-center rounded-xl bg-primary text-primary-foreground">
                      <CopyPlus className="size-6" />
                    </div>
                  </div>
                </div>
              </div>

              <div className="flex min-h-[92px] flex-1 flex-col justify-between px-1 pt-3">
                <div>
                  <p className="text-[15px] font-semibold">
                    {t.createCustomTemplate}
                  </p>
                  <p className="mt-1 text-xs leading-[1.45] text-muted-foreground">
                    {t.templateManagerHint}
                  </p>
                </div>

                <div className="grid grid-cols-2 gap-2 pt-2.5">
                  <Button
                    type="button"
                    className="h-8.5"
                    onClick={onCreateCustomTemplate}
                  >
                    <CopyPlus className="size-4" />
                    {t.newTemplate}
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    className="h-8.5 bg-background"
                    onClick={() => fileInputRef.current?.click()}
                  >
                    <FileUp className="size-4" />
                    {t.importTemplate}
                  </Button>
                </div>
              </div>
            </CardContent>
          </Card>

          {paginatedTemplates.map((item) => {
            const isSelected = selectedIdSet.has(item.id);
            const isDefaultTemplate = defaultTemplateId === item.id;

            return (
              <ViewTransitionBoundary
                key={item.id}
                enter="fade-in"
                exit="fade-out"
                default="none"
              >
                <div className="group h-full select-none">
                <div
                  className={cn(
                    "flex h-full flex-col rounded-[24px] border border-border/80 bg-card p-2.5 shadow-none transition-colors duration-200 group-hover:border-border group-hover:bg-accent/20",
                    isSelected && "border-primary bg-accent/20",
                  )}
                >
                  <button
                    type="button"
                    className="cursor-pointer select-none rounded-[18px] text-left outline-none"
                    aria-pressed={isSelecting ? isSelected : undefined}
                    onClick={() => handleTemplateCardAction(item)}
                  >
                    <div className="rounded-[18px] bg-muted/55 p-2">
                      <ViewTransitionBoundary
                        name={`template-preview-${item.id}`}
                        share="morph"
                        default="none"
                      >
                        <div className="relative mx-auto h-[258px] w-[182px] overflow-hidden rounded-[14px] border border-zinc-200 bg-white">
                          <div
                            className="pointer-events-none absolute left-0 top-0 origin-top-left scale-[0.224]"
                            style={{ width: "210mm", height: "297mm" }}
                          >
                            <ResumePreview
                              locale={locale}
                              t={t}
                              resume={resume}
                              fontFamily={item.typography.fontFamily}
                              fontSize={item.typography.fontSize}
                              template={item}
                              variant="thumbnail"
                            />
                          </div>

                          {isSelecting ? (
                            <span
                              className={cn(
                                "absolute left-3 top-3 flex size-7 items-center justify-center rounded-full border bg-background/92 backdrop-blur transition-colors",
                                isSelected
                                  ? "border-primary bg-primary text-primary-foreground"
                                  : "border-border/80 text-muted-foreground",
                              )}
                            >
                              <Check className="size-3.5" />
                            </span>
                          ) : null}
                        </div>
                      </ViewTransitionBoundary>
                    </div>
                  </button>

                  <div className="flex min-h-[92px] flex-1 flex-col justify-between px-1 pt-3">
                    <button
                      type="button"
                      className="cursor-pointer select-none text-left outline-none"
                      onClick={() => handleTemplateCardAction(item)}
                    >
                      <p className="truncate text-[15px] font-semibold">
                        {item.name}
                      </p>
                      <p className="mt-1 truncate text-xs text-muted-foreground">
                        {item.description || t.templateDescriptionFallback}
                      </p>
                    </button>

                    <div className="mt-2 flex items-center justify-between gap-2">
                      {item.isBuiltIn ? (
                        <Badge className="h-7 bg-transparent px-2.5 text-[11px] font-medium text-muted-foreground shadow-none">
                          <Sparkles className="mr-1 size-3.5" />
                          {t.builtInTemplate}
                        </Badge>
                      ) : (
                        <span />
                      )}

                      {isSelecting ? (
                        isSelected && !item.isBuiltIn ? (
                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            className="h-7 rounded-full border-red-600 bg-red-600 px-2.5 text-[11px] text-white hover:border-red-700 hover:bg-red-700 hover:text-white"
                            onClick={() => requestDelete([item.id])}
                          >
                            <Trash2 className="size-3.5" />
                          </Button>
                        ) : null
                      ) : isDefaultTemplate ? (
                        <Badge
                          variant="outline"
                          className="h-7 rounded-full border-border/80 bg-muted px-2.5 text-[11px] font-medium text-muted-foreground"
                        >
                          {t.defaultTemplateLabel}
                        </Badge>
                      ) : (
                        <Button
                          type="button"
                          size="sm"
                          className="h-7 rounded-full px-2.5 text-[11px]"
                          onClick={() => onSetDefaultTemplate(item.id)}
                        >
                          {t.setDefaultTemplate}
                        </Button>
                      )}
                    </div>
                  </div>
                </div>
                </div>
              </ViewTransitionBoundary>
            );
          })}
        </div>

        <GalleryPagination
          currentPage={safeCurrentPage}
          totalPages={totalPages}
          locale={locale}
          onPageChange={setCurrentPage}
        />
      </section>
    );
  }

  return (
    <div className="grid gap-4">
      <input
        ref={fileInputRef}
        type="file"
        accept=".json,application/json"
        className="hidden"
        onChange={handleImportChange}
      />

      {mode === "editor" && activeTemplate ? (
        <Card className="rounded-[30px] border border-border/60 bg-card shadow-[0_18px_60px_-48px_rgba(15,23,42,0.5)]">
          <CardContent className="template-editor-scroll p-0">
            <div className="sticky top-0 z-20 border-b border-border/40 bg-card/95 px-5 py-4 backdrop-blur">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="truncate text-2xl font-semibold tracking-[-0.05em] text-foreground">
                      {activeTemplate.name}
                    </p>
                    <Badge
                      variant="outline"
                      className="h-7 rounded-xl border-transparent bg-muted/70 px-2.5 text-[11px] font-medium text-muted-foreground shadow-none"
                    >
                      {activeTemplate.isBuiltIn
                        ? t.templateReadonlyStatus
                        : t.templateEditableStatus}
                    </Badge>
                    {activeTemplate.id === defaultTemplateId ? (
                      <Badge
                        variant="outline"
                        className="h-7 rounded-xl border-transparent bg-muted/70 px-2.5 text-[11px] font-medium text-muted-foreground shadow-none"
                      >
                        {t.defaultTemplateLabel}
                      </Badge>
                    ) : null}
                  </div>
                  <p className="mt-1 max-w-[460px] text-sm leading-6 text-muted-foreground">
                    {activeTemplate.description ||
                      t.templateDescriptionFallback}
                  </p>
                </div>

                <div className="flex shrink-0 flex-wrap items-center gap-2">
                  {activeTemplate.isBuiltIn ? (
                    <Button
                      type="button"
                      size="sm"
                      className="h-9 rounded-2xl px-3 shadow-none"
                      onClick={onCreateCustomTemplate}
                    >
                      <CopyPlus className="size-4" />
                      {t.createEditableCopy}
                    </Button>
                  ) : null}
                  {activeTemplate.id !== defaultTemplateId ? (
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      className="h-9 rounded-2xl border-transparent bg-background/80 px-3 shadow-none ring-1 ring-border/35 hover:bg-muted"
                      onClick={() => onSetDefaultTemplate(activeTemplate.id)}
                    >
                      {t.setDefaultTemplate}
                    </Button>
                  ) : null}
                </div>
              </div>
            </div>

            <div className="grid gap-4 p-5">
            <TemplateEditorPanel
              title={t.templatePreviewModules}
              description={t.templatePreviewModulesHint}
              defaultOpen={false}
              badge={
                <Badge
                  variant="outline"
                  className="shrink-0 rounded-xl border-transparent bg-background/85 px-2.5 py-1.5 text-xs font-medium text-muted-foreground shadow-none ring-1 ring-border/35"
                >
                  {locale === "zh"
                    ? `${previewModuleCount} 个模块`
                    : `${previewModuleCount} modules`}
                </Badge>
              }
            >
              <div className="grid gap-5">

              <div className="grid gap-2.5 rounded-[22px] bg-background/65 p-3.5 ring-1 ring-border/20">
                <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                  {t.templateAddableModules}
                </p>
                <div className="flex flex-wrap gap-2">
                  {previewSectionKinds.map((kind) => (
                    <Button
                      key={kind}
                      type="button"
                      variant="outline"
                      size="sm"
                      className="h-8 rounded-2xl border-transparent bg-muted/45 px-3 text-xs shadow-none transition-colors hover:bg-muted"
                      onClick={() => onAddPreviewSection?.(kind)}
                      disabled={!onAddPreviewSection}
                    >
                      <Plus className="size-3" />
                      {t.sectionTitles[kind]}
                    </Button>
                  ))}
                </div>
              </div>

              <div className="grid gap-2">
                <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                  {t.templateCurrentModules}
                </p>
                <div className="flex h-10 items-center rounded-2xl bg-background/85 px-3 text-sm shadow-none ring-1 ring-border/30">
                  <span className="font-semibold text-foreground">
                    {t.basicInfo}
                  </span>
                </div>

                {resume.sections.map((section) => (
                  <div
                    key={section.id}
                    className="flex h-10 max-w-full items-center justify-between gap-2 rounded-2xl bg-background/85 pl-3 pr-2 text-sm shadow-none ring-1 ring-border/30"
                  >
                    <span className="min-w-0 truncate font-semibold text-foreground">
                      {getSectionTitle(section, t)}
                    </span>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="size-6 shrink-0 rounded-full text-muted-foreground hover:text-destructive"
                      onClick={() => onRemovePreviewSection?.(section.id)}
                      disabled={!onRemovePreviewSection}
                      aria-label={t.deleteSection}
                    >
                      <Trash2 className="size-3" />
                    </Button>
                  </div>
                ))}
              </div>
              </div>
            </TemplateEditorPanel>

            <div className="grid gap-3 rounded-[26px] bg-muted/15 p-3">
              {!isTemplateReadonly ? (
                <TemplateEditorPanel
                  title={t.templateInfoPanel}
                  defaultOpen={false}
                  badge={
                    <Badge
                      variant="outline"
                      className="h-7 rounded-xl border-transparent bg-background/80 px-2.5 text-[11px] font-medium text-muted-foreground shadow-none ring-1 ring-border/35"
                    >
                      {t.customTemplate}
                    </Badge>
                  }
                >
                  <div className="grid gap-4">

                    <label className="grid gap-2 text-sm">
                      <span className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                        {t.templateName}
                      </span>
                      <Input
                        className="h-11 rounded-xl bg-background/80 shadow-none"
                        value={activeTemplate.name}
                        onChange={(event) =>
                          onUpdateTemplate(activeTemplate.id, {
                            name: event.target.value,
                          })
                        }
                      />
                    </label>

                    <label className="grid gap-2 text-sm">
                      <span className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                        {t.templateDescription}
                      </span>
                      <Textarea
                        className="rounded-xl bg-background/80 shadow-none"
                        rows={3}
                        value={activeTemplate.description}
                        onChange={(event) =>
                          onUpdateTemplate(activeTemplate.id, {
                            description: event.target.value,
                          })
                        }
                      />
                    </label>
                  </div>
                </TemplateEditorPanel>
              ) : null}

              <Tabs
                    value={editorTab}
                    onValueChange={(value) =>
                      setEditorTab(value as TemplateEditorTab)
                    }
                    className="gap-4"
                  >
                    <TabsList className="w-full justify-start rounded-[18px] bg-background/80 p-1.5 shadow-sm ring-1 ring-border/35">
                      <TabsTrigger value="layout">
                        {t.templateLayoutTab}
                      </TabsTrigger>
                      <TabsTrigger value="typography">
                        {t.templateTypographyTab}
                      </TabsTrigger>
                      <TabsTrigger value="visual">
                        {t.templateVisualTab}
                      </TabsTrigger>
                      <TabsTrigger value="images">
                        {t.templateImagesTab}
                      </TabsTrigger>
                    </TabsList>

                    <TabsContent
                      value="layout"
                      className="grid gap-3"
                    >
                      <TemplateEditorPanel
                        title={t.templateLayoutStructure}
                        defaultOpen
                      >
                        <div className="grid gap-3 md:grid-cols-2">
                        <label className="grid gap-2 rounded-[18px] bg-muted/35 p-3 text-sm shadow-[inset_0_1px_0_rgba(255,255,255,0.55)]">
                          <span className="font-medium">
                            {t.basicInfoLayout}
                          </span>
                          <Select
                            value={activeTemplate.layout.basicInfo}
                            disabled={isTemplateReadonly}
                            onValueChange={(value) =>
                              updateLayout({
                                basicInfo: value as ResumeBasicInfoLayout,
                              })
                            }
                          >
                            <SelectTrigger className="h-10 rounded-lg bg-background">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="centered">
                                {t.basicInfoLayoutCentered}
                              </SelectItem>
                              <SelectItem value="profile">
                                {t.basicInfoLayoutProfile}
                              </SelectItem>
                              <SelectItem value="sidebar">
                                {t.basicInfoLayoutSidebar}
                              </SelectItem>
                            </SelectContent>
                          </Select>
                        </label>

                        <label className="grid gap-2 rounded-[18px] bg-muted/35 p-3 text-sm shadow-[inset_0_1px_0_rgba(255,255,255,0.55)]">
                          <span className="font-medium">
                            {t.sectionTemplateStyle}
                          </span>
                          <Select
                            value={activeTemplate.layout.section}
                            disabled={isTemplateReadonly}
                            onValueChange={(value) =>
                              updateLayout({
                                section: value as ResumeSectionTemplateStyle,
                              })
                            }
                          >
                            <SelectTrigger className="h-10 rounded-lg bg-background">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="ruled">
                                {t.sectionStyleRuled}
                              </SelectItem>
                              <SelectItem value="boxed">
                                {t.sectionStyleBoxed}
                              </SelectItem>
                              <SelectItem value="accent">
                                {t.sectionStyleAccent}
                              </SelectItem>
                              <SelectItem value="plain">
                                {t.sectionStylePlain}
                              </SelectItem>
                              <SelectItem value="band">
                                {t.sectionStyleBand}
                              </SelectItem>
                            </SelectContent>
                          </Select>
                        </label>

                        </div>
                      </TemplateEditorPanel>

                      <TemplateEditorPanel
                        title={t.templateAvatarControls}
                        defaultOpen={false}
                      >
                        <div className="grid gap-3 md:grid-cols-2">
                        <label className="grid gap-2 rounded-[18px] bg-muted/35 p-3 text-sm shadow-[inset_0_1px_0_rgba(255,255,255,0.55)]">
                          <span className="font-medium">
                            {t.avatarPosition}
                          </span>
                          <Select
                            value={activeTemplate.layout.avatarPosition}
                            disabled={isTemplateReadonly}
                            onValueChange={(value) =>
                              updateLayout({
                                avatarPosition: value as ResumeAvatarPosition,
                              })
                            }
                          >
                            <SelectTrigger className="h-10 rounded-lg bg-background">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="right">
                                {t.avatarPositionRight}
                              </SelectItem>
                              <SelectItem value="left">
                                {t.avatarPositionLeft}
                              </SelectItem>
                              <SelectItem value="center">
                                {t.avatarPositionCenter}
                              </SelectItem>
                            </SelectContent>
                          </Select>
                        </label>

                        <label className="grid gap-2 rounded-[18px] bg-muted/35 p-3 text-sm shadow-[inset_0_1px_0_rgba(255,255,255,0.55)]">
                          <span className="font-medium">{t.avatarShape}</span>
                          <Select
                            value={activeTemplate.layout.avatarShape}
                            disabled={isTemplateReadonly}
                            onValueChange={(value) =>
                              updateLayout({
                                avatarShape: value as ResumeAvatarShape,
                              })
                            }
                          >
                            <SelectTrigger className="h-10 rounded-lg bg-background">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="rounded">
                                {t.avatarShapeRounded}
                              </SelectItem>
                              <SelectItem value="circle">
                                {t.avatarShapeCircle}
                              </SelectItem>
                              <SelectItem value="square">
                                {t.avatarShapeSquare}
                              </SelectItem>
                            </SelectContent>
                          </Select>
                        </label>

                        <TemplateSliderField
                          label={t.avatarWidth}
                          min={16}
                          max={48}
                          step={0.5}
                          value={activeTemplate.layout.avatarWidth}
                          displayValue={`${activeTemplate.layout.avatarWidth.toFixed(1)}mm`}
                          onChange={(value) =>
                            updateLayout({ avatarWidth: value })
                          }
                          disabled={isTemplateReadonly}
                        />
                        <TemplateSliderField
                          label={t.avatarHeight}
                          min={16}
                          max={56}
                          step={0.5}
                          value={activeTemplate.layout.avatarHeight}
                          displayValue={`${activeTemplate.layout.avatarHeight.toFixed(1)}mm`}
                          onChange={(value) =>
                            updateLayout({ avatarHeight: value })
                          }
                          disabled={isTemplateReadonly}
                        />
                        <TemplateSliderField
                          label={t.avatarOffsetX}
                          min={-40}
                          max={40}
                          step={0.5}
                          value={activeTemplate.layout.avatarOffsetX}
                          displayValue={`${activeTemplate.layout.avatarOffsetX.toFixed(1)}mm`}
                          onChange={(value) =>
                            updateLayout({ avatarOffsetX: value })
                          }
                          disabled={isTemplateReadonly}
                        />
                        <TemplateSliderField
                          label={t.avatarOffsetY}
                          min={-40}
                          max={40}
                          step={0.5}
                          value={activeTemplate.layout.avatarOffsetY}
                          displayValue={`${activeTemplate.layout.avatarOffsetY.toFixed(1)}mm`}
                          onChange={(value) =>
                            updateLayout({ avatarOffsetY: value })
                          }
                          disabled={isTemplateReadonly}
                        />
                        <TemplateSliderField
                          label={t.avatarBorderWidth}
                          min={0}
                          max={8}
                          step={0.5}
                          value={activeTemplate.layout.avatarBorderWidth}
                          displayValue={`${activeTemplate.layout.avatarBorderWidth.toFixed(1)}px`}
                          onChange={(value) =>
                            updateLayout({ avatarBorderWidth: value })
                          }
                          disabled={isTemplateReadonly}
                        />
                        <TemplateColorField
                          label={t.avatarBorderColor}
                          value={activeTemplate.layout.avatarBorderColor}
                          onChange={(value) =>
                            updateLayout({ avatarBorderColor: value })
                          }
                          disabled={isTemplateReadonly}
                        />
                        </div>
                      </TemplateEditorPanel>

                      <TemplateEditorPanel
                        title={t.templateSpacingRules}
                        defaultOpen={false}
                      >
                        <div className="grid gap-3 md:grid-cols-2">
                          <TemplateSliderField
                            label={t.pagePaddingTop}
                            min={8}
                            max={20}
                            step={1}
                            value={activeTemplate.settings.pagePaddingTop}
                            displayValue={`${activeTemplate.settings.pagePaddingTop}mm`}
                            onChange={(value) =>
                              updateSettings({ pagePaddingTop: value })
                            }
                            disabled={isTemplateReadonly}
                          />
                          <TemplateSliderField
                            label={t.pagePaddingX}
                            min={8}
                            max={18}
                            step={1}
                            value={activeTemplate.settings.pagePaddingX}
                            displayValue={`${activeTemplate.settings.pagePaddingX}mm`}
                            onChange={(value) =>
                              updateSettings({ pagePaddingX: value })
                            }
                            disabled={isTemplateReadonly}
                          />
                          <TemplateSliderField
                            label={t.pagePaddingBottom}
                            min={8}
                            max={18}
                            step={1}
                            value={activeTemplate.settings.pagePaddingBottom}
                            displayValue={`${activeTemplate.settings.pagePaddingBottom}mm`}
                            onChange={(value) =>
                              updateSettings({ pagePaddingBottom: value })
                            }
                            disabled={isTemplateReadonly}
                          />
                          <TemplateSliderField
                            label={t.sectionGap}
                            min={0.8}
                            max={2.4}
                            step={0.1}
                            value={activeTemplate.settings.sectionGap}
                            displayValue={`${activeTemplate.settings.sectionGap.toFixed(1)}em`}
                            onChange={(value) =>
                              updateSettings({ sectionGap: value })
                            }
                            disabled={isTemplateReadonly}
                          />
                          <TemplateSliderField
                            label={t.itemGap}
                            min={0.4}
                            max={1.8}
                            step={0.1}
                            value={activeTemplate.settings.itemGap}
                            displayValue={`${activeTemplate.settings.itemGap.toFixed(1)}em`}
                            onChange={(value) => updateSettings({ itemGap: value })}
                            disabled={isTemplateReadonly}
                          />
                          <TemplateSliderField
                            label={t.bodyLineHeight}
                            min={1.4}
                            max={2.2}
                            step={0.05}
                            value={activeTemplate.settings.bodyLineHeight}
                            displayValue={activeTemplate.settings.bodyLineHeight.toFixed(
                              2,
                            )}
                            onChange={(value) =>
                              updateSettings({ bodyLineHeight: value })
                            }
                            disabled={isTemplateReadonly}
                          />
                          <TemplateSliderField
                            label={t.dividerThickness}
                            min={0.5}
                            max={3}
                            step={0.5}
                            value={activeTemplate.settings.dividerThickness}
                            displayValue={`${activeTemplate.settings.dividerThickness.toFixed(1)}px`}
                            onChange={(value) =>
                              updateSettings({ dividerThickness: value })
                            }
                            disabled={isTemplateReadonly}
                          />
                        </div>
                      </TemplateEditorPanel>
                    </TabsContent>

                    <TabsContent
                      value="typography"
                      className={cn(
                        "grid gap-3",
                        isTemplateReadonly && "pointer-events-none opacity-70",
                      )}
                    >
                      <div className="grid gap-3 md:grid-cols-2">
                        <label className="grid gap-2 rounded-[18px] bg-muted/35 p-3 text-sm shadow-[inset_0_1px_0_rgba(255,255,255,0.55)]">
                          <span className="font-medium">{t.fontFamily}</span>
                          <Select
                            value={activeTemplate.typography.fontFamily}
                            onValueChange={(value) =>
                              onUpdateTemplate(activeTemplate.id, {
                                typography: {
                                  ...activeTemplate.typography,
                                  fontFamily: value as ResumeFontFamily,
                                },
                              })
                            }
                          >
                            <SelectTrigger className="h-10 rounded-lg bg-background">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="inter">{t.fontInter}</SelectItem>
                              <SelectItem value="serif">{t.fontSerif}</SelectItem>
                              <SelectItem value="plex">{t.fontPlex}</SelectItem>
                            </SelectContent>
                          </Select>
                        </label>

                        <label className="grid gap-2 rounded-[18px] bg-muted/35 p-3 text-sm shadow-[inset_0_1px_0_rgba(255,255,255,0.55)]">
                          <span className="font-medium">{t.fontSize}</span>
                          <Select
                            value={String(activeTemplate.typography.fontSize)}
                            onValueChange={(value) =>
                              onUpdateTemplate(activeTemplate.id, {
                                typography: {
                                  ...activeTemplate.typography,
                                  fontSize: Number(value),
                                },
                              })
                            }
                          >
                            <SelectTrigger className="h-10 rounded-lg bg-background">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              {fontSizeOptions.map((size) => (
                                <SelectItem key={size} value={String(size)}>
                                  {size}pt
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </label>
                      </div>

                      <TemplateSliderField
                        label={t.nameSize}
                        min={1.6}
                        max={2.8}
                        step={0.05}
                        value={activeTemplate.settings.nameScale}
                        displayValue={getScaleLabel(
                          activeTemplate.typography.fontSize,
                          activeTemplate.settings.nameScale,
                        )}
                        onChange={(value) =>
                          updateSettings({ nameScale: value })
                        }
                      />
                      <TemplateSliderField
                        label={t.sectionTitleSize}
                        min={0.75}
                        max={1.6}
                        step={0.05}
                        value={activeTemplate.settings.sectionTitleScale}
                        displayValue={getScaleLabel(
                          activeTemplate.typography.fontSize,
                          activeTemplate.settings.sectionTitleScale,
                        )}
                        onChange={(value) =>
                          updateSettings({ sectionTitleScale: value })
                        }
                      />
                      <TemplateSliderField
                        label={t.itemTitleSize}
                        min={0.85}
                        max={1.4}
                        step={0.05}
                        value={activeTemplate.settings.itemTitleScale}
                        displayValue={getScaleLabel(
                          activeTemplate.typography.fontSize,
                          activeTemplate.settings.itemTitleScale,
                        )}
                        onChange={(value) =>
                          updateSettings({ itemTitleScale: value })
                        }
                      />
                      <TemplateSliderField
                        label={t.metaSize}
                        min={0.75}
                        max={1.15}
                        step={0.05}
                        value={activeTemplate.settings.metaScale}
                        displayValue={getScaleLabel(
                          activeTemplate.typography.fontSize,
                          activeTemplate.settings.metaScale,
                        )}
                        onChange={(value) =>
                          updateSettings({ metaScale: value })
                        }
                      />
                      <TemplateSliderField
                        label={t.bodySize}
                        min={0.85}
                        max={1.2}
                        step={0.05}
                        value={activeTemplate.settings.bodyScale}
                        displayValue={getScaleLabel(
                          activeTemplate.typography.fontSize,
                          activeTemplate.settings.bodyScale,
                        )}
                        onChange={(value) =>
                          updateSettings({ bodyScale: value })
                        }
                      />
                    </TabsContent>

                    <TabsContent
                      value="visual"
                      className={cn(
                        "grid gap-3",
                        isTemplateReadonly && "pointer-events-none opacity-70",
                      )}
                    >
                      <TemplateColorField
                        label={t.pageBackground}
                        value={activeTemplate.settings.pageBackground}
                        onChange={(value) =>
                          updateSettings({ pageBackground: value })
                        }
                      />
                      <TemplateColorField
                        label={t.surfaceColor}
                        value={activeTemplate.settings.surfaceColor}
                        onChange={(value) =>
                          updateSettings({ surfaceColor: value })
                        }
                      />
                      <TemplateColorField
                        label={t.headingColor}
                        value={activeTemplate.settings.headingColor}
                        onChange={(value) =>
                          updateSettings({ headingColor: value })
                        }
                      />
                      <TemplateColorField
                        label={t.bodyColor}
                        value={activeTemplate.settings.bodyColor}
                        onChange={(value) =>
                          updateSettings({ bodyColor: value })
                        }
                      />
                      <TemplateColorField
                        label={t.mutedColor}
                        value={activeTemplate.settings.mutedColor}
                        onChange={(value) =>
                          updateSettings({ mutedColor: value })
                        }
                      />
                      <TemplateColorField
                        label={t.dividerColor}
                        value={activeTemplate.settings.dividerColor}
                        onChange={(value) =>
                          updateSettings({ dividerColor: value })
                        }
                      />
                    </TabsContent>

                    <TabsContent
                      value="images"
                      className={cn(
                        "grid gap-3",
                        isTemplateReadonly && "pointer-events-none opacity-70",
                      )}
                    >
                      <Button
                        type="button"
                        variant="outline"
                        className="h-11 justify-center rounded-xl border-dashed bg-background"
                        onClick={addTemplateImage}
                      >
                        <ImagePlus className="size-4" />
                        {t.addTemplateImage}
                      </Button>

                      {(activeTemplate.layout.images ?? []).length === 0 ? (
                        <div className="rounded-xl border border-dashed border-border/80 bg-muted/20 p-4 text-sm text-muted-foreground">
                          {t.templateImagesEmpty}
                        </div>
                      ) : null}

                      {(activeTemplate.layout.images ?? []).map((image, index) => {
                        const fileInputId = `template-image-${image.id}`;

                        return (
                          <div
                            key={image.id}
                            className="grid gap-4 rounded-[22px] bg-background/80 p-4 shadow-[0_16px_48px_-42px_rgba(15,23,42,0.8),inset_0_0_0_1px_hsl(var(--border)/0.35)]"
                          >
                            <div className="flex items-start gap-3">
                              <div
                                className="flex h-16 w-20 shrink-0 items-center justify-center overflow-hidden rounded-xl border bg-gradient-to-br from-background via-muted/30 to-muted/60 text-center text-[10px] font-medium text-muted-foreground"
                                style={{
                                  borderColor: image.borderColor,
                                  borderWidth: image.borderWidth,
                                  borderRadius: image.borderRadius,
                                }}
                              >
                                {image.src ? (
                                  <img
                                    src={image.src}
                                    alt={image.alt || image.name}
                                    className="size-full"
                                    style={{ objectFit: image.objectFit }}
                                    draggable={false}
                                  />
                                ) : (
                                  <div className="grid place-items-center gap-1 px-2">
                                    <ImagePlus className="size-4 opacity-70" />
                                    <span className="max-w-16 truncate">
                                      {image.name || t.imagePlaceholder}
                                    </span>
                                  </div>
                                )}
                              </div>

                              <div className="grid min-w-0 flex-1 gap-2">
                                <Input
                                  value={image.name}
                                  onChange={(event) =>
                                    updateTemplateImage(image.id, {
                                      name: event.target.value,
                                    })
                                  }
                                  placeholder={`${t.imageName} ${index + 1}`}
                                />
                                <Input
                                  value={image.src}
                                  onChange={(event) =>
                                    updateTemplateImage(image.id, {
                                      src: event.target.value,
                                    })
                                  }
                                  placeholder={t.imageUrl}
                                />
                              </div>

                              <Button
                                type="button"
                                variant="ghost"
                                size="icon"
                                className="shrink-0 text-muted-foreground hover:text-destructive"
                                onClick={() => removeTemplateImage(image.id)}
                                aria-label={t.removeImage}
                              >
                                <Trash2 className="size-4" />
                              </Button>
                            </div>

                            <div className="flex flex-wrap gap-2">
                              <Input
                                id={fileInputId}
                                type="file"
                                accept="image/*"
                                className="hidden"
                                onChange={(event) => {
                                  void handleTemplateImageUpload(
                                    image.id,
                                    event.target.files?.[0],
                                  );
                                  event.target.value = "";
                                }}
                              />
                              <Button
                                type="button"
                                variant="outline"
                                size="sm"
                                className="rounded-full bg-background"
                                asChild
                              >
                                <label htmlFor={fileInputId} className="cursor-pointer">
                                  <FileUp className="size-4" />
                                  {t.uploadImage}
                                </label>
                              </Button>
                              <Select
                                value={image.objectFit}
                                onValueChange={(value) =>
                                  updateTemplateImage(image.id, {
                                    objectFit: value as ResumeTemplateImageFit,
                                  })
                                }
                              >
                                <SelectTrigger className="h-8 w-[126px] rounded-full bg-background text-xs">
                                  <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                  <SelectItem value="contain">
                                    {t.imageFitContain}
                                  </SelectItem>
                                  <SelectItem value="cover">
                                    {t.imageFitCover}
                                  </SelectItem>
                                </SelectContent>
                              </Select>
                            </div>

                            <div className="grid gap-3 md:grid-cols-2">
                              <TemplateSliderField
                                label={t.imagePositionX}
                                min={0}
                                max={210}
                                step={0.5}
                                value={image.x}
                                displayValue={`${image.x}mm`}
                                onChange={(value) =>
                                  updateTemplateImage(image.id, { x: value })
                                }
                              />
                              <TemplateSliderField
                                label={t.imagePositionY}
                                min={0}
                                max={297}
                                step={0.5}
                                value={image.y}
                                displayValue={`${image.y}mm`}
                                onChange={(value) =>
                                  updateTemplateImage(image.id, { y: value })
                                }
                              />
                              <TemplateSliderField
                                label={t.imageWidth}
                                min={6}
                                max={120}
                                step={0.5}
                                value={image.width}
                                displayValue={`${image.width}mm`}
                                onChange={(value) =>
                                  updateTemplateImage(image.id, { width: value })
                                }
                              />
                              <TemplateSliderField
                                label={t.imageHeight}
                                min={6}
                                max={120}
                                step={0.5}
                                value={image.height}
                                displayValue={`${image.height}mm`}
                                onChange={(value) =>
                                  updateTemplateImage(image.id, { height: value })
                                }
                              />
                              <TemplateSliderField
                                label={t.imageOpacity}
                                min={0.05}
                                max={1}
                                step={0.05}
                                value={image.opacity}
                                displayValue={image.opacity.toFixed(2)}
                                onChange={(value) =>
                                  updateTemplateImage(image.id, { opacity: value })
                                }
                              />
                              <TemplateSliderField
                                label={t.imageBorderWidth}
                                min={0}
                                max={8}
                                step={0.5}
                                value={image.borderWidth}
                                displayValue={`${image.borderWidth.toFixed(1)}px`}
                                onChange={(value) =>
                                  updateTemplateImage(image.id, {
                                    borderWidth: value,
                                  })
                                }
                              />
                              <TemplateSliderField
                                label={t.imageBorderRadius}
                                min={0}
                                max={32}
                                step={1}
                                value={image.borderRadius}
                                displayValue={`${image.borderRadius}px`}
                                onChange={(value) =>
                                  updateTemplateImage(image.id, {
                                    borderRadius: value,
                                  })
                                }
                              />
                              <TemplateColorField
                                label={t.imageBorderColor}
                                value={image.borderColor}
                                onChange={(value) =>
                                  updateTemplateImage(image.id, {
                                    borderColor: value,
                                  })
                                }
                              />
                            </div>
                          </div>
                        );
                      })}
                    </TabsContent>
              </Tabs>
            </div>
            </div>
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
