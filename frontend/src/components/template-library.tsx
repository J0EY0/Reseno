import {
  Check,
  ChevronDown,
  CircleUserRound,
  CopyPlus,
  FileUp,
  Image as ImageIcon,
  ImagePlus,
  LayoutTemplate,
  ListMinus,
  Palette,
  PencilLine,
  SlidersHorizontal,
  SquareDashed,
  Sparkles,
  Trash2,
  Type,
  type LucideIcon,
} from "lucide-react";
import {
  useDeferredValue,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type ReactNode,
} from "react";
import { Link } from "react-router-dom";

import type { AppMessages } from "@/i18n";
import { readAvatarFileAsDataUrl } from "@/lib/avatar";
import { createId } from "@/lib/resume";
import {
  getResumeFontSizeInPoints,
  resumeFontSizeOptions,
} from "@/lib/templates";
import { cn } from "@/lib/utils";
import type {
  ResumeAvatarPosition,
  ResumeBasicInfoLayout,
  ResumeData,
  ResumeFontFamily,
  ResumeListItemLayout,
  ResumeSectionTemplateStyle,
  ResumeTemplateDefinition,
  ResumeTemplateImageElement,
  ResumeTemplateImageFit,
  ResumeTemplateLayout,
  ResumeTemplateSettings,
  ResumeTimelineItemLayout,
} from "@/types/resume";

import { ConfirmActionDialog } from "@/components/confirm-action-dialog";
import { GalleryPagination } from "@/components/gallery-pagination";
import { GalleryToolbar } from "@/components/gallery-toolbar";
import { ResumePreview } from "@/components/preview/resume-preview";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Empty, EmptyDescription } from "@/components/ui/empty";
import { Card, CardContent } from "@/components/ui/card";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { Input } from "@/components/ui/input";
import {
  Field,
  FieldGroup,
  FieldLabel,
  FieldLegend,
  FieldSet,
  FieldTitle,
} from "@/components/ui/field";
import {
  InputGroup,
  InputGroupAddon,
  InputGroupInput,
  InputGroupText,
} from "@/components/ui/input-group";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";
import { Spinner } from "@/components/ui/spinner";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { ViewTransitionBoundary } from "@/components/view-transition";
import { useGalleryGridPageSize } from "@/components/use-gallery-grid-page-size";
import { useGalleryUrlState } from "@/components/use-gallery-url-state";

type TemplateEditorTab = "layout" | "typography" | "visual" | "images";
type TemplatePageMarginPreset = "compact" | "standard" | "relaxed";
type TemplateContentDensityPreset = "compact" | "standard" | "relaxed";
type TemplateContentDensity = TemplateContentDensityPreset | "custom";
type TemplateDividerStyle = "thin" | "medium" | "bold";

const pageMarginPresetValues: Record<
  TemplatePageMarginPreset,
  Pick<
    ResumeTemplateSettings,
    "pagePaddingTop" | "pagePaddingX" | "pagePaddingBottom"
  >
> = {
  compact: {
    pagePaddingTop: 10,
    pagePaddingX: 10,
    pagePaddingBottom: 10,
  },
  standard: {
    pagePaddingTop: 14,
    pagePaddingX: 12,
    pagePaddingBottom: 12,
  },
  relaxed: {
    pagePaddingTop: 18,
    pagePaddingX: 16,
    pagePaddingBottom: 16,
  },
};

const dividerStyleValues: Record<TemplateDividerStyle, number> = {
  thin: 1,
  medium: 1.5,
  bold: 2.5,
};

const contentDensityValues: Record<
  TemplateContentDensityPreset,
  Pick<ResumeTemplateSettings, "sectionGap" | "itemGap" | "bodyLineHeight">
> = {
  compact: {
    sectionGap: 0.9,
    itemGap: 0.6,
    bodyLineHeight: 1.45,
  },
  standard: {
    sectionGap: 1.2,
    itemGap: 0.8,
    bodyLineHeight: 1.6,
  },
  relaxed: {
    sectionGap: 1.5,
    itemGap: 1,
    bodyLineHeight: 1.75,
  },
};

const readonlyDisabledControlClassName =
  "disabled:pointer-events-auto disabled:cursor-not-allowed";

function getPageMarginPreset(
  settings: ResumeTemplateSettings,
): TemplatePageMarginPreset {
  if (
    settings.pagePaddingTop >= 16 ||
    settings.pagePaddingX >= 15 ||
    settings.pagePaddingBottom >= 15
  ) {
    return "relaxed";
  }

  if (
    settings.pagePaddingTop <= 11 ||
    settings.pagePaddingX <= 10 ||
    settings.pagePaddingBottom <= 10
  ) {
    return "compact";
  }

  return "standard";
}

function getDividerStyle(settings: ResumeTemplateSettings): TemplateDividerStyle {
  if (settings.dividerThickness >= 2) {
    return "bold";
  }

  if (settings.dividerThickness > 1) {
    return "medium";
  }

  return "thin";
}

function getContentDensity(
  settings: ResumeTemplateSettings,
): TemplateContentDensity {
  const densities = Object.keys(
    contentDensityValues,
  ) as TemplateContentDensityPreset[];

  // Numeric settings remain the source of truth. Manual tuning and Smart
  // One Page must not be mislabeled as the nearest named preset.
  return (
    densities.find((density) => {
      const preset = contentDensityValues[density];

      return (
        Math.abs(settings.sectionGap - preset.sectionGap) <= 0.01 &&
        Math.abs(settings.itemGap - preset.itemGap) <= 0.01 &&
        Math.abs(settings.bodyLineHeight - preset.bodyLineHeight) <= 0.01
      );
    }) ?? "custom"
  );
}

function TemplateTabLabel({
  icon: Icon,
  children,
}: {
  icon: LucideIcon;
  children: ReactNode;
}) {
  return (
    <span className="inline-flex max-w-full min-w-0 translate-y-1 items-center justify-center gap-1.5">
      <Icon className="size-4 shrink-0" />
      <span className="min-w-0 truncate">{children}</span>
    </span>
  );
}

function TemplateSelectRow({
  icon: Icon,
  label,
  children,
}: {
  icon: LucideIcon;
  label: string;
  children: ReactNode;
}) {
  return (
    <div className="grid min-h-[58px] grid-cols-[minmax(0,1fr)_minmax(148px,190px)] items-center gap-4">
      <div className="flex min-w-0 items-center gap-3">
        <Icon className="size-4 shrink-0 text-muted-foreground" />
        <span className="min-w-0 truncate text-sm font-medium text-foreground">
          {label}
        </span>
      </div>
      {children}
    </div>
  );
}

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
      className="rounded-(--radius-card) bg-muted/20 ring-1 ring-border/25"
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
        "grid min-h-[58px] grid-cols-[minmax(0,1fr)_minmax(148px,190px)] items-center gap-4 py-2",
        disabled && "cursor-not-allowed text-muted-foreground",
      )}
    >
      <div className="min-w-0">
        <span className="text-sm font-medium">{label}</span>
        <span className="mt-0.5 block text-xs text-muted-foreground">
          {displayValue}
        </span>
      </div>
      <Slider
        min={min}
        max={max}
        step={step}
        value={[value]}
        onValueChange={(next) => onChange(next[0] ?? value)}
        disabled={disabled}
        className={disabled ? "cursor-not-allowed" : undefined}
      />
    </div>
  );
}

function clampTemplateImageValue(
  value: number,
  min: number,
  max: number,
  step: number,
) {
  const clamped = Math.min(Math.max(value, min), max);
  const stepped = min + Math.round((clamped - min) / step) * step;

  return Number(Math.min(Math.max(stepped, min), max).toFixed(4));
}

function formatTemplateImageValue(value: number) {
  return String(Number(value.toFixed(4)));
}

function TemplateImageNumberField({
  id,
  label,
  orientation = "vertical",
  min,
  max,
  step,
  value,
  unit,
  onChange,
  disabled = false,
}: {
  id: string;
  label: string;
  orientation?: "vertical" | "horizontal";
  min: number;
  max: number;
  step: number;
  value: number;
  unit: string;
  onChange: (value: number) => void;
  disabled?: boolean;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  const unitId = `${id}-unit`;
  const inputValue = draft ?? formatTemplateImageValue(value);
  const parsedDraft = Number(inputValue);
  const isDraftValid =
    inputValue.trim() !== "" &&
    Number.isFinite(parsedDraft) &&
    parsedDraft >= min &&
    parsedDraft <= max;

  function updateDraft(nextDraft: string) {
    setDraft(nextDraft);
    const parsed = Number(nextDraft);

    // Keep the preview and autosave state current while preserving the
    // user's temporary input string until the field is committed.
    if (nextDraft.trim() !== "" && Number.isFinite(parsed)) {
      onChange(clampTemplateImageValue(parsed, min, max, step));
    }
  }

  function commitDraft() {
    const currentDraft = draft ?? formatTemplateImageValue(value);
    const parsed = Number(currentDraft);
    const nextValue =
      currentDraft.trim() !== "" && Number.isFinite(parsed)
        ? clampTemplateImageValue(parsed, min, max, step)
        : value;

    onChange(nextValue);
    setDraft(null);
  }

  return (
    <Field
      orientation={orientation}
      className={cn(
        "gap-1.5",
        orientation === "horizontal" && "min-w-0 gap-2",
      )}
      data-disabled={disabled || undefined}
    >
      <FieldLabel
        htmlFor={id}
        className={cn(
          "text-xs",
          orientation === "horizontal"
            ? "min-w-0 leading-tight"
            : "whitespace-nowrap",
        )}
      >
        {label}
      </FieldLabel>
      <InputGroup
        className={orientation === "horizontal" ? "w-28 shrink-0" : undefined}
        data-disabled={disabled || undefined}
      >
        <InputGroupInput
          id={id}
          type="number"
          inputMode="decimal"
          min={min}
          max={max}
          step={step}
          value={inputValue}
          onFocus={() => setDraft(formatTemplateImageValue(value))}
          onChange={(event) => updateDraft(event.target.value)}
          onBlur={commitDraft}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.currentTarget.blur();
            }

            if (event.key === "Escape") {
              event.preventDefault();
              setDraft(null);
            }
          }}
          aria-describedby={unitId}
          aria-invalid={!isDraftValid || undefined}
          disabled={disabled}
          className="text-right tabular-nums [appearance:textfield] [&::-webkit-inner-spin-button]:m-0 [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:m-0 [&::-webkit-outer-spin-button]:appearance-none"
        />
        <InputGroupAddon align="inline-end">
          <InputGroupText id={unitId} translate="no">
            {unit}
          </InputGroupText>
        </InputGroupAddon>
      </InputGroup>
    </Field>
  );
}

function TemplateImageSliderField({
  id,
  label,
  min,
  max,
  step,
  value,
  onChange,
  disabled = false,
}: {
  id: string;
  label: string;
  min: number;
  max: number;
  step: number;
  value: number;
  onChange: (value: number) => void;
  disabled?: boolean;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  const unitId = `${id}-unit`;
  const minPercent = min * 100;
  const maxPercent = max * 100;
  const stepPercent = step * 100;
  const percentValue = Math.round(value * 100);
  const inputValue = draft ?? String(percentValue);
  const parsedDraft = Number(inputValue);
  const isDraftValid =
    inputValue.trim() !== "" &&
    Number.isFinite(parsedDraft) &&
    parsedDraft >= minPercent &&
    parsedDraft <= maxPercent;
  const displayValue = `${percentValue}%`;

  function updateDraft(nextDraft: string) {
    setDraft(nextDraft);
    const parsed = Number(nextDraft);

    if (nextDraft.trim() !== "" && Number.isFinite(parsed)) {
      onChange(
        clampTemplateImageValue(
          parsed,
          minPercent,
          maxPercent,
          stepPercent,
        ) / 100,
      );
    }
  }

  function commitDraft() {
    const currentDraft = draft ?? String(percentValue);
    const parsed = Number(currentDraft);
    const nextPercent =
      currentDraft.trim() !== "" && Number.isFinite(parsed)
        ? clampTemplateImageValue(
            parsed,
            minPercent,
            maxPercent,
            stepPercent,
          )
        : percentValue;

    onChange(nextPercent / 100);
    setDraft(null);
  }

  return (
    <Field
      orientation="horizontal"
      data-slot="template-image-slider-field"
      className="grid grid-cols-[5.5rem_minmax(0,1fr)_7rem] items-center gap-3"
      data-disabled={disabled || undefined}
    >
      <FieldLabel htmlFor={id} className="w-auto text-xs">
        {label}
      </FieldLabel>
      <Slider
        min={min}
        max={max}
        step={step}
        value={[value]}
        onValueChange={(next) => {
          setDraft(null);
          onChange(next[0] ?? value);
        }}
        disabled={disabled}
        thumbProps={{
          "aria-label": label,
          "aria-valuetext": displayValue,
        }}
        className={cn("min-w-0", disabled && "cursor-not-allowed")}
      />
      <InputGroup
        data-template-image-slider-value="true"
        className="w-28 shrink-0"
        data-disabled={disabled || undefined}
      >
        <InputGroupInput
          id={id}
          type="number"
          inputMode="decimal"
          min={minPercent}
          max={maxPercent}
          step={stepPercent}
          value={inputValue}
          onFocus={() => setDraft(String(percentValue))}
          onChange={(event) => updateDraft(event.target.value)}
          onBlur={commitDraft}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.currentTarget.blur();
            }

            if (event.key === "Escape") {
              event.preventDefault();
              setDraft(null);
            }
          }}
          aria-describedby={unitId}
          aria-invalid={!isDraftValid || undefined}
          disabled={disabled}
          className="text-right tabular-nums [appearance:textfield] [&::-webkit-inner-spin-button]:m-0 [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:m-0 [&::-webkit-outer-spin-button]:appearance-none"
        />
        <InputGroupAddon align="inline-end">
          <InputGroupText id={unitId} translate="no">
            %
          </InputGroupText>
        </InputGroupAddon>
      </InputGroup>
    </Field>
  );
}

function TemplateImageColorField({
  id,
  label,
  value,
  onChange,
  disabled = false,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  return (
    <Field
      orientation="horizontal"
      className="min-w-0 gap-2"
      data-disabled={disabled || undefined}
    >
      <FieldLabel htmlFor={id} className="min-w-0 text-xs leading-tight">
        {label}
      </FieldLabel>
      <InputGroup
        className="w-28 shrink-0"
        data-disabled={disabled || undefined}
      >
        <InputGroupInput
          id={id}
          type="color"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          disabled={disabled}
          className={cn(
            "m-1 size-7 flex-none cursor-pointer rounded-sm p-0",
            disabled && readonlyDisabledControlClassName,
          )}
        />
        <InputGroupAddon align="inline-end" className="min-w-0 pl-1 pr-2">
          <InputGroupText className="truncate font-mono text-[10px] uppercase tracking-[0.04em]">
            {value}
          </InputGroupText>
        </InputGroupAddon>
      </InputGroup>
    </Field>
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
        "grid min-h-[58px] grid-cols-[minmax(0,1fr)_minmax(148px,190px)] items-center gap-4 py-2",
        disabled && "cursor-not-allowed text-muted-foreground",
      )}
    >
      <div className="min-w-0">
        <span className="block text-sm font-medium">{label}</span>
        <span className="rounded-md border border-border/70 bg-background px-2 py-1 font-mono text-[11px] uppercase tracking-[0.08em] text-muted-foreground">
          {value}
        </span>
      </div>
      <div className="flex min-w-0 items-center gap-3">
        <Input
          type="color"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          className={cn(
            "h-10 w-14 shrink-0 cursor-pointer rounded-lg border border-border/70 bg-background p-1",
            disabled && readonlyDisabledControlClassName,
          )}
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
  defaultName: string,
  layout?: ResumeTemplateLayout,
): ResumeTemplateImageElement {
  const placeOnLeft = layout?.avatarPosition === "right";

  return {
    id: createId("image"),
    name: `${defaultName} ${index}`,
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
  t,
  resume,
  templates,
  defaultTemplateId,
  activeTemplateId,
  isImporting,
  isCreating,
  settingDefaultTemplateId,
  onOpenTemplate,
  onSetDefaultTemplate,
  onCreateCustomTemplate,
  onImportTemplates,
  onUpdateTemplate,
  onDeleteTemplate,
  onBulkDeleteTemplates,
}: {
  mode: "gallery" | "editor";
  t: AppMessages;
  resume: ResumeData;
  templates: ResumeTemplateDefinition[];
  defaultTemplateId: string;
  activeTemplateId: string;
  isImporting: boolean;
  isCreating: boolean;
  settingDefaultTemplateId: string | null;
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
}) {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [isSelecting, setIsSelecting] = useState(false);
  const [pendingDeleteIds, setPendingDeleteIds] = useState<string[]>([]);
  const [isDeleteDialogOpen, setIsDeleteDialogOpen] = useState(false);
  const [editorTab, setEditorTab] = useState<TemplateEditorTab>("layout");
  // Expansion belongs to the editor UI and must not leak into saved template data.
  const [expandedImageIdByTemplate, setExpandedImageIdByTemplate] =
    useState<Partial<Record<string, string>>>({});
  const [imageNameDraft, setImageNameDraft] = useState<{
    imageKey: string;
    value: string;
  } | null>(null);
  const { currentPage, searchQuery, setCurrentPage, setSearchQuery } =
    useGalleryUrlState();
  const { gridRef, pageSize } = useGalleryGridPageSize({ fixedItems: 0 });
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

    const currentImages = activeTemplate.layout.images;
    const currentImageNames = new Set(currentImages.map((image) => image.name));
    let nextImageIndex = 1;

    while (currentImageNames.has(`${t.imageDefaultName} ${nextImageIndex}`)) {
      nextImageIndex += 1;
    }

    const nextImage = createTemplateImageElement(
      nextImageIndex,
      t.imageDefaultName,
      activeTemplate.layout,
    );

    setExpandedImageIdByTemplate((current) => ({
      ...current,
      [activeTemplate.id]: nextImage.id,
    }));
    updateLayout({
      images: [...currentImages, nextImage],
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
      images: activeTemplate.layout.images.map((image) =>
        image.id === imageId ? { ...image, ...patch } : image,
      ),
    });
  }

  function commitTemplateImageName(imageId: string, imageKey: string) {
    if (imageNameDraft?.imageKey !== imageKey) {
      return;
    }

    updateTemplateImage(imageId, { name: imageNameDraft.value });
    setImageNameDraft(null);
  }

  function removeTemplateImage(imageId: string) {
    if (!activeTemplate || activeTemplate.isBuiltIn) {
      return;
    }

    const imageKey = `${activeTemplate.id}:${imageId}`;

    setExpandedImageIdByTemplate((current) => {
      if (current[activeTemplate.id] !== imageId) {
        return current;
      }

      const next = { ...current };
      delete next[activeTemplate.id];
      return next;
    });
    setImageNameDraft((current) =>
      current?.imageKey === imageKey ? null : current,
    );
    updateLayout({
      images: activeTemplate.layout.images.filter((image) => image.id !== imageId),
    });
  }

  function setTemplateImageExpanded(imageId: string, open: boolean) {
    if (!activeTemplate) {
      return;
    }

    setExpandedImageIdByTemplate((current) => {
      if (open) {
        return {
          ...current,
          [activeTemplate.id]: imageId,
        };
      }

      if (current[activeTemplate.id] !== imageId) {
        return current;
      }

      const next = { ...current };
      delete next[activeTemplate.id];
      return next;
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

  if (mode === "gallery") {
    return (
      <section className="rounded-(--radius-workspace) border border-border bg-muted/35 p-3.5 text-foreground sm:p-4">
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
          disabled={isImporting}
          onChange={handleImportChange}
        />

        <GalleryToolbar
          searchLabel={t.searchTemplatesLabel}
          searchName="template-search"
          searchPlaceholder={t.searchTemplatesPlaceholder}
          searchValue={searchQuery}
          onSearchChange={(value) => {
            setSearchQuery(value);
          }}
          isSelecting={isSelecting}
          onToggleSelecting={toggleSelecting}
          selectedCount={selectedTemplateIds.length}
          selectLabel={t.selectItems}
          cancelLabel={t.cancelSelection}
          bulkDeleteLabel={t.bulkDelete}
          onBulkDelete={() => requestDelete(selectedTemplateIds)}
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
                {isImporting ? t.importing : t.importTemplate}
              </Button>
              <Button
                type="button"
                disabled={isImporting || isCreating}
                onClick={onCreateCustomTemplate}
              >
                {isCreating ? (
                  <Spinner data-icon="inline-start" aria-label={t.newTemplate} />
                ) : (
                  <CopyPlus data-icon="inline-start" />
                )}
                {t.newTemplate}
              </Button>
            </>
          }
        />

        <div
          ref={gridRef}
          className="grid auto-rows-fr grid-cols-[repeat(auto-fit,minmax(208px,228px))] gap-4"
        >
          {paginatedTemplates.length === 0 ? (
            <Empty className="col-span-full min-h-[390px] border border-border/70 bg-card/55">
              <EmptyDescription className="font-medium">
                {templates.length === 0 ? t.emptyTemplates : t.emptyTemplateSearch}
              </EmptyDescription>
            </Empty>
          ) : null}

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
                <div className="group relative h-full select-none">
                  <div
                    className={cn(
                      "flex h-full flex-col rounded-(--radius-card) border border-border/80 bg-card p-2.5 shadow-none transition-colors duration-200 group-hover:border-border group-hover:bg-accent/20",
                      isSelected && "border-primary bg-accent/20",
                    )}
                  >
                    <Link
                      to={`/template/${item.id}`}
                      role={isSelecting ? "button" : undefined}
                      aria-label={item.name}
                      className="block cursor-pointer select-none rounded-[18px] text-left outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                      aria-pressed={isSelecting ? isSelected : undefined}
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
                          onOpenTemplate(item.id);
                        }
                      }}
                      onKeyDown={(event) => {
                        if (isSelecting && event.key === " ") {
                          event.preventDefault();
                          toggleSelected(item.id);
                        }
                      }}
                    >
                      <div className="rounded-[18px] bg-muted/55 p-2">
                        <ViewTransitionBoundary
                          name={`template-preview-${item.id}`}
                          share="morph"
                          default="none"
                        >
                          <div className="relative mx-auto h-[258px] w-[182px] overflow-hidden rounded-[14px] border border-zinc-200 bg-white">
                            <div
                              aria-hidden="true"
                              className="pointer-events-none absolute left-0 top-0 origin-top-left scale-[0.224]"
                              style={{ width: "210mm", height: "297mm" }}
                            >
                              <ResumePreview
                                t={t}
                                resume={resume}
                                fontFamily={item.typography.fontFamily}
                                fontSize={item.typography.fontSize}
                                template={item}
                                variant="thumbnail"
                                showEmptyTemplateImagePlaceholders
                              />
                            </div>

                            {isSelecting ? (
                              <span
                                aria-hidden="true"
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
                    </Link>

                    <div className="flex min-h-[92px] flex-1 flex-col justify-between px-1 pt-3">
                      <div className="min-w-0">
                        <p
                          className="truncate text-[15px] font-semibold"
                          title={item.name}
                        >
                          {item.name}
                        </p>
                        <p
                          className="mt-1 line-clamp-2 min-h-8 text-xs text-muted-foreground"
                          title={
                            item.description || t.templateDescriptionFallback
                          }
                        >
                          {item.description || t.templateDescriptionFallback}
                        </p>
                      </div>

                      <div className="mt-2 flex items-center justify-between gap-2">
                        {item.isBuiltIn ? (
                          <Badge className="h-7 bg-transparent px-2.5 text-[11px] font-medium text-muted-foreground shadow-none">
                            <Sparkles className="mr-1 size-3.5" />
                            {t.builtInTemplate}
                          </Badge>
                        ) : (
                          <span />
                        )}

                        {isSelecting ? null : isDefaultTemplate ? (
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
                            disabled={settingDefaultTemplateId !== null}
                            onClick={() => onSetDefaultTemplate(item.id)}
                          >
                            {settingDefaultTemplateId === item.id ? (
                              <Spinner
                                data-icon="inline-start"
                                aria-label={t.setDefaultTemplate}
                              />
                            ) : null}
                            {t.setDefaultTemplate}
                          </Button>
                        )}
                      </div>
                    </div>
                  </div>
                  {isSelecting && isSelected && !item.isBuiltIn ? (
                    <Button
                      type="button"
                      variant="destructive"
                      size="icon-sm"
                      className="absolute right-8 top-8 z-10 size-7 rounded-full backdrop-blur"
                      onClick={() => requestDelete([item.id])}
                      aria-label={t.confirmDeleteAction}
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

  return (
    <div className="grid gap-4">
      <input
        ref={fileInputRef}
        type="file"
        accept=".json,application/json"
        className="hidden"
        disabled={isImporting}
        onChange={handleImportChange}
      />

      {mode === "editor" && activeTemplate ? (
        <Card className="overflow-hidden rounded-[30px] border border-border/80 bg-card shadow-[0_18px_60px_-48px_rgba(15,23,42,0.5)]">
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
                      className="h-9 rounded-lg px-3 shadow-none"
                      disabled={isImporting || isCreating}
                      onClick={onCreateCustomTemplate}
                    >
                      {isCreating ? (
                        <Spinner
                          data-icon="inline-start"
                          aria-label={t.createEditableCopy}
                        />
                      ) : (
                        <CopyPlus data-icon="inline-start" />
                      )}
                      {t.createEditableCopy}
                    </Button>
                  ) : null}
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className={cn(
                      "h-9 rounded-lg border-transparent px-3 shadow-none",
                      activeTemplate.id === defaultTemplateId
                        ? "bg-muted/70 text-muted-foreground ring-0 hover:bg-muted/70 hover:text-muted-foreground focus-visible:ring-0 disabled:pointer-events-auto disabled:cursor-default disabled:opacity-100"
                        : "bg-background/80 ring-1 ring-border/35 hover:bg-muted",
                    )}
                    onClick={() => onSetDefaultTemplate(activeTemplate.id)}
                    disabled={
                      activeTemplate.id === defaultTemplateId ||
                      settingDefaultTemplateId !== null
                    }
                  >
                    {settingDefaultTemplateId === activeTemplate.id ? (
                      <Spinner
                        data-icon="inline-start"
                        aria-label={t.setDefaultTemplate}
                      />
                    ) : null}
                    {activeTemplate.id === defaultTemplateId
                      ? t.defaultTemplateLabel
                      : t.setDefaultTemplate}
                  </Button>
                </div>
              </div>
            </div>

            <div className="grid gap-4 p-5">
              <div className="grid gap-3">
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
                  className="grid gap-0"
                >
                  <TabsList
                    variant="line"
                    className="grid w-full grid-cols-[1fr_0.82fr_0.9fr_1.28fr] gap-0 rounded-none border-0 border-b border-border/70 p-0 text-muted-foreground group-data-[orientation=horizontal]/tabs:h-12"
                  >
                    <TabsTrigger
                      value="layout"
                      className="h-12 min-w-0 items-center rounded-none border-transparent px-1.5 py-0 text-sm font-semibold after:bottom-[-1px]!"
                    >
                      <TemplateTabLabel icon={LayoutTemplate}>
                        {t.templateLayoutTab}
                      </TemplateTabLabel>
                    </TabsTrigger>
                    <TabsTrigger
                      value="typography"
                      className="h-12 min-w-0 items-center rounded-none border-transparent px-1.5 py-0 text-sm font-semibold after:bottom-[-1px]!"
                    >
                      <TemplateTabLabel icon={Type}>
                        {t.templateTypographyTab}
                      </TemplateTabLabel>
                    </TabsTrigger>
                    <TabsTrigger
                      value="visual"
                      className="h-12 min-w-0 items-center rounded-none border-transparent px-1.5 py-0 text-sm font-semibold after:bottom-[-1px]!"
                    >
                      <TemplateTabLabel icon={Palette}>
                        {t.templateVisualTab}
                      </TemplateTabLabel>
                    </TabsTrigger>
                    <TabsTrigger
                      value="images"
                      className="h-12 min-w-0 items-center rounded-none border-transparent px-1.5 py-0 text-sm font-semibold after:bottom-[-1px]!"
                    >
                      <TemplateTabLabel icon={Sparkles}>
                        {t.templateImagesTab}
                      </TemplateTabLabel>
                    </TabsTrigger>
                  </TabsList>

                    <TabsContent value="layout" className="m-0 px-1 py-4">
                      <div className="grid">
                        <TemplateSelectRow
                          icon={ImageIcon}
                          label={t.basicInfoLayout}
                        >
                          <Select
                            value={activeTemplate.layout.basicInfo}
                            disabled={isTemplateReadonly}
                            onValueChange={(value) =>
                              updateLayout({
                                basicInfo: value as ResumeBasicInfoLayout,
                              })
                            }
                          >
                            <SelectTrigger className="w-full">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="centered">
                                {t.basicInfoLayoutCentered}
                              </SelectItem>
                              <SelectItem value="left">
                                {t.basicInfoLayoutLeft}
                              </SelectItem>
                              <SelectItem value="split">
                                {t.basicInfoLayoutSplit}
                              </SelectItem>
                              <SelectItem value="profile">
                                {t.basicInfoLayoutProfile}
                              </SelectItem>
                              <SelectItem value="sidebar">
                                {t.basicInfoLayoutSidebar}
                              </SelectItem>
                            </SelectContent>
                          </Select>
                        </TemplateSelectRow>

                        <TemplateSelectRow
                          icon={SlidersHorizontal}
                          label={t.sectionTemplateStyle}
                        >
                          <Select
                            value={activeTemplate.layout.section}
                            disabled={isTemplateReadonly}
                            onValueChange={(value) =>
                              updateLayout({
                                section: value as ResumeSectionTemplateStyle,
                              })
                            }
                          >
                            <SelectTrigger className="w-full">
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
                        </TemplateSelectRow>

                        <TemplateSelectRow
                          icon={LayoutTemplate}
                          label={t.timelineItemLayout}
                        >
                          <Select
                            value={activeTemplate.layout.timelineItemLayout}
                            disabled={isTemplateReadonly}
                            onValueChange={(value) =>
                              updateLayout({
                                timelineItemLayout:
                                  value as ResumeTimelineItemLayout,
                              })
                            }
                          >
                            <SelectTrigger className="w-full">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="split">
                                {t.timelineItemLayoutSplit}
                              </SelectItem>
                              <SelectItem value="stacked">
                                {t.timelineItemLayoutStacked}
                              </SelectItem>
                              <SelectItem value="compact">
                                {t.timelineItemLayoutCompact}
                              </SelectItem>
                            </SelectContent>
                          </Select>
                        </TemplateSelectRow>

                        <TemplateSelectRow
                          icon={ListMinus}
                          label={t.listItemLayout}
                        >
                          <Select
                            value={activeTemplate.layout.listItemLayout}
                            disabled={isTemplateReadonly}
                            onValueChange={(value) =>
                              updateLayout({
                                listItemLayout: value as ResumeListItemLayout,
                              })
                            }
                          >
                            <SelectTrigger className="w-full">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="list">
                                {t.listItemLayoutList}
                              </SelectItem>
                              <SelectItem value="inline">
                                {t.listItemLayoutInline}
                              </SelectItem>
                              <SelectItem value="columns">
                                {t.listItemLayoutColumns}
                              </SelectItem>
                            </SelectContent>
                          </Select>
                        </TemplateSelectRow>

                        <TemplateSelectRow
                          icon={CircleUserRound}
                          label={t.avatarPosition}
                        >
                          <Select
                            value={activeTemplate.layout.avatarPosition}
                            disabled={isTemplateReadonly}
                            onValueChange={(value) =>
                              updateLayout({
                                avatarPosition: value as ResumeAvatarPosition,
                              })
                            }
                          >
                            <SelectTrigger className="w-full">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="none">
                                {t.avatarPositionNone}
                              </SelectItem>
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
                        </TemplateSelectRow>

                        <TemplateSelectRow
                          icon={SquareDashed}
                          label={t.pageMargin}
                        >
                          <Select
                            value={getPageMarginPreset(activeTemplate.settings)}
                            disabled={isTemplateReadonly}
                            onValueChange={(value) =>
                              updateSettings(
                                pageMarginPresetValues[
                                  value as TemplatePageMarginPreset
                                ],
                              )
                            }
                          >
                            <SelectTrigger className="w-full">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="compact">
                                {t.pageMarginCompact}
                              </SelectItem>
                              <SelectItem value="standard">
                                {t.pageMarginStandard}
                              </SelectItem>
                              <SelectItem value="relaxed">
                                {t.pageMarginRelaxed}
                              </SelectItem>
                            </SelectContent>
                          </Select>
                        </TemplateSelectRow>

                        <TemplateSelectRow
                          icon={SlidersHorizontal}
                          label={t.templateContentDensity}
                        >
                          <Select
                            value={getContentDensity(activeTemplate.settings)}
                            disabled={isTemplateReadonly}
                            onValueChange={(value) => {
                              if (value === "custom") {
                                return;
                              }

                              updateSettings(
                                contentDensityValues[
                                  value as TemplateContentDensityPreset
                                ],
                              );
                            }}
                          >
                            <SelectTrigger className="w-full">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="compact">
                                {t.templateDensityCompact}
                              </SelectItem>
                              <SelectItem value="standard">
                                {t.templateDensityStandard}
                              </SelectItem>
                              <SelectItem value="relaxed">
                                {t.templateDensityRelaxed}
                              </SelectItem>
                              <SelectItem value="custom" disabled>
                                {t.templateDensityCustom}
                              </SelectItem>
                            </SelectContent>
                          </Select>
                        </TemplateSelectRow>

                        <TemplateSelectRow
                          icon={ListMinus}
                          label={t.templateDividerStyle}
                        >
                          <Select
                            value={getDividerStyle(activeTemplate.settings)}
                            disabled={isTemplateReadonly}
                            onValueChange={(value) =>
                              updateSettings({
                                dividerThickness:
                                  dividerStyleValues[
                                    value as TemplateDividerStyle
                                  ],
                              })
                            }
                          >
                            <SelectTrigger className="w-full">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="thin">
                                {t.templateDividerThin}
                              </SelectItem>
                              <SelectItem value="medium">
                                {t.templateDividerMedium}
                              </SelectItem>
                              <SelectItem value="bold">
                                {t.templateDividerBold}
                              </SelectItem>
                            </SelectContent>
                          </Select>
                        </TemplateSelectRow>
                      </div>

                    </TabsContent>

                    <TabsContent
                      value="typography"
                      className={cn(
                        "m-0 grid gap-1 px-1 py-4",
                        isTemplateReadonly && "opacity-70",
                      )}
                    >
                      <div className="grid">
                        <label className="grid min-h-[58px] grid-cols-[minmax(0,1fr)_minmax(148px,190px)] items-center gap-4 py-2 text-sm">
                          <span className="min-w-0 truncate font-medium">
                            {t.fontFamily}
                          </span>
                          <Select
                            value={activeTemplate.typography.fontFamily}
                            disabled={isTemplateReadonly}
                            onValueChange={(value) =>
                              onUpdateTemplate(activeTemplate.id, {
                                typography: {
                                  ...activeTemplate.typography,
                                  fontFamily: value as ResumeFontFamily,
                                },
                              })
                            }
                          >
                            <SelectTrigger className="w-full">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectGroup>
                                <SelectItem value="inter">
                                  {t.fontInter}
                                </SelectItem>
                                <SelectItem value="noto_sans_sc">
                                  {t.fontNotoSans}
                                </SelectItem>
                                <SelectItem value="serif">
                                  {t.fontSerif}
                                </SelectItem>
                                <SelectItem value="plex">
                                  {t.fontPlex}
                                </SelectItem>
                              </SelectGroup>
                            </SelectContent>
                          </Select>
                        </label>

                        <label className="grid min-h-[58px] grid-cols-[minmax(0,1fr)_minmax(148px,190px)] items-center gap-4 py-2 text-sm">
                          <span className="min-w-0 truncate font-medium">
                            {t.fontSize}
                          </span>
                          <Select
                            value={String(activeTemplate.typography.fontSize)}
                            disabled={isTemplateReadonly}
                            onValueChange={(value) =>
                              onUpdateTemplate(activeTemplate.id, {
                                typography: {
                                  ...activeTemplate.typography,
                                  fontSize: Number(value),
                                },
                              })
                            }
                          >
                            <SelectTrigger className="w-full">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              {resumeFontSizeOptions.map((size) => (
                                <SelectItem key={size} value={String(size)}>
                                  {getResumeFontSizeInPoints(size)} pt
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
                        disabled={isTemplateReadonly}
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
                        disabled={isTemplateReadonly}
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
                        disabled={isTemplateReadonly}
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
                        disabled={isTemplateReadonly}
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
                        disabled={isTemplateReadonly}
                      />
                    </TabsContent>

                    <TabsContent
                      value="visual"
                      className={cn(
                        "m-0 grid gap-1 px-1 py-4",
                        isTemplateReadonly && "opacity-70",
                      )}
                    >
                      <TemplateColorField
                        label={t.pageBackground}
                        value={activeTemplate.settings.pageBackground}
                        onChange={(value) =>
                          updateSettings({ pageBackground: value })
                        }
                        disabled={isTemplateReadonly}
                      />
                      <TemplateColorField
                        label={t.surfaceColor}
                        value={activeTemplate.settings.surfaceColor}
                        onChange={(value) =>
                          updateSettings({ surfaceColor: value })
                        }
                        disabled={isTemplateReadonly}
                      />
                      <TemplateColorField
                        label={t.headingColor}
                        value={activeTemplate.settings.headingColor}
                        onChange={(value) =>
                          updateSettings({ headingColor: value })
                        }
                        disabled={isTemplateReadonly}
                      />
                      <TemplateColorField
                        label={t.bodyColor}
                        value={activeTemplate.settings.bodyColor}
                        onChange={(value) =>
                          updateSettings({ bodyColor: value })
                        }
                        disabled={isTemplateReadonly}
                      />
                      <TemplateColorField
                        label={t.mutedColor}
                        value={activeTemplate.settings.mutedColor}
                        onChange={(value) =>
                          updateSettings({ mutedColor: value })
                        }
                        disabled={isTemplateReadonly}
                      />
                      <TemplateColorField
                        label={t.dividerColor}
                        value={activeTemplate.settings.dividerColor}
                        onChange={(value) =>
                          updateSettings({ dividerColor: value })
                        }
                        disabled={isTemplateReadonly}
                      />
                    </TabsContent>

                    <TabsContent
                      value="images"
                      className={cn(
                        "m-0 grid gap-3 px-1 py-4",
                        isTemplateReadonly && "opacity-70",
                      )}
                    >
                      <Button
                        type="button"
                        variant="outline"
                        className={cn(
                          "h-11 justify-center rounded-xl border-dashed bg-background",
                          readonlyDisabledControlClassName,
                        )}
                        onClick={addTemplateImage}
                        disabled={isTemplateReadonly}
                      >
                        <ImagePlus data-icon="inline-start" />
                        {t.addTemplateImage}
                      </Button>

                      {activeTemplate.layout.images.map((image, index) => {
                        const imageKey = `${activeTemplate.id}:${image.id}`;
                        const isImageExpanded =
                          expandedImageIdByTemplate[activeTemplate.id] ===
                          image.id;
                        const isEditingImageName =
                          imageNameDraft?.imageKey === imageKey;
                        const hasImageBorder = image.borderWidth > 0;
                        const fileInputId = `template-image-${image.id}`;
                        const imageNameInputId = `${fileInputId}-name`;
                        const imageFitInputId = `${fileInputId}-fit`;
                        const positionXMax = Math.max(0, 210 - image.width);
                        const positionYMax = Math.max(0, 297 - image.height);
                        const widthMax = Math.max(
                          6,
                          Math.min(120, 210 - image.x),
                        );
                        const heightMax = Math.max(
                          6,
                          Math.min(120, 297 - image.y),
                        );

                        return (
                          <Collapsible
                            key={`${activeTemplate.id}:${image.id}`}
                            open={isImageExpanded}
                            onOpenChange={(open) =>
                              setTemplateImageExpanded(image.id, open)
                            }
                            role="group"
                            aria-label={`${t.templateImageControls} ${index + 1}`}
                            className="@container/image-card overflow-hidden rounded-lg bg-muted/35 shadow-xs"
                          >
                            <div
                              data-slot="template-image-card-header"
                              className="grid grid-cols-[40px_minmax(0,1fr)_auto] items-center gap-3 p-3"
                            >
                              <div
                                data-slot="template-image-thumbnail"
                                className="flex size-10 shrink-0 items-center justify-center overflow-hidden rounded-md border bg-background text-muted-foreground"
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
                                  <ImagePlus className="size-4 opacity-70" />
                                )}
                              </div>

                              {isEditingImageName ? (
                                <Field className="min-w-0 gap-1.5">
                                  <FieldLabel
                                    htmlFor={imageNameInputId}
                                    className="sr-only"
                                  >
                                    {t.imageName}
                                  </FieldLabel>
                                  <Input
                                    id={imageNameInputId}
                                    value={imageNameDraft.value}
                                    onChange={(event) =>
                                      setImageNameDraft((current) =>
                                        current?.imageKey === imageKey
                                          ? {
                                              ...current,
                                              value: event.target.value,
                                            }
                                          : current,
                                      )
                                    }
                                    onBlur={() =>
                                      commitTemplateImageName(
                                        image.id,
                                        imageKey,
                                      )
                                    }
                                    onKeyDown={(event) => {
                                      if (event.key === "Enter") {
                                        event.currentTarget.blur();
                                      }

                                      if (event.key === "Escape") {
                                        event.preventDefault();
                                        setImageNameDraft(null);
                                      }
                                    }}
                                    placeholder={`${t.imageName} ${index + 1}`}
                                    autoFocus
                                    className="font-medium"
                                  />
                                </Field>
                              ) : (
                                <div className="flex min-w-0 items-center gap-1">
                                  <p
                                    className="min-w-0 truncate text-sm font-semibold"
                                    title={image.name}
                                  >
                                    {image.name || `${t.imageName} ${index + 1}`}
                                  </p>
                                  <Button
                                    type="button"
                                    variant="ghost"
                                    size="icon-sm"
                                    className="shrink-0 text-muted-foreground"
                                    onClick={() =>
                                      setImageNameDraft({
                                        imageKey,
                                        value: image.name,
                                      })
                                    }
                                    aria-label={t.editImageName}
                                    disabled={isTemplateReadonly}
                                  >
                                    <PencilLine data-icon="icon-only" />
                                  </Button>
                                </div>
                              )}

                              <div className="flex items-center gap-1">
                                <Button
                                  type="button"
                                  variant="ghost"
                                  size="icon-sm"
                                  className={cn(
                                    "shrink-0 text-muted-foreground hover:text-destructive",
                                    readonlyDisabledControlClassName,
                                  )}
                                  onClick={() => removeTemplateImage(image.id)}
                                  aria-label={t.removeImage}
                                  disabled={isTemplateReadonly}
                                >
                                  <Trash2 data-icon="icon-only" />
                                </Button>
                                <CollapsibleTrigger asChild>
                                  <Button
                                    type="button"
                                    variant="ghost"
                                    size="icon-sm"
                                    className="group shrink-0 text-muted-foreground"
                                  >
                                    <ChevronDown
                                      data-icon="icon-only"
                                      aria-hidden="true"
                                      className="transition-transform group-data-[state=open]:rotate-180"
                                    />
                                    <span className="sr-only group-data-[state=open]:hidden">
                                      {t.expandImageSettings}
                                    </span>
                                    <span className="sr-only hidden group-data-[state=open]:inline">
                                      {t.collapseImageSettings}
                                    </span>
                                  </Button>
                                </CollapsibleTrigger>
                              </div>
                            </div>

                            <CollapsibleContent className="collapsible-content">
                              <FieldGroup
                                data-slot="template-image-card-content"
                                className="collapsible-content-inner gap-5 p-3"
                              >
                                <div className="grid gap-3">
                                  <Field
                                    orientation="horizontal"
                                    role="group"
                                    aria-label={t.imageSourceLabel}
                                    className="min-w-0 gap-3"
                                  >
                                    <FieldTitle className="shrink-0 text-xs">
                                      {t.imageSourceLabel}
                                    </FieldTitle>
                                    <div className="ml-auto flex min-w-0 flex-wrap items-center justify-end gap-1">
                                      <Input
                                        id={fileInputId}
                                        type="file"
                                        accept="image/*"
                                        className="hidden"
                                        disabled={isTemplateReadonly}
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
                                        onClick={() =>
                                          document
                                            .getElementById(fileInputId)
                                            ?.click()
                                        }
                                        className={cn(
                                          "justify-center bg-background",
                                          readonlyDisabledControlClassName,
                                        )}
                                        disabled={isTemplateReadonly}
                                      >
                                        <FileUp data-icon="inline-start" />
                                        {image.src
                                          ? t.replaceImage
                                          : t.uploadImage}
                                      </Button>
                                    </div>
                                  </Field>
                                  <Field
                                    orientation="horizontal"
                                    className="min-w-0 gap-3"
                                  >
                                    <FieldLabel
                                      htmlFor={imageFitInputId}
                                      className="shrink-0 text-xs"
                                    >
                                      {t.imageFitLabel}
                                    </FieldLabel>
                                    <Select
                                      value={image.objectFit}
                                      disabled={isTemplateReadonly}
                                      onValueChange={(value) =>
                                        updateTemplateImage(image.id, {
                                          objectFit:
                                            value as ResumeTemplateImageFit,
                                        })
                                      }
                                    >
                                      <SelectTrigger
                                        id={imageFitInputId}
                                        size="sm"
                                        className="ml-auto w-40 max-w-full"
                                      >
                                        <SelectValue />
                                      </SelectTrigger>
                                      <SelectContent>
                                        <SelectGroup>
                                          <SelectItem value="contain">
                                            {t.imageFitContain}
                                          </SelectItem>
                                          <SelectItem value="cover">
                                            {t.imageFitCover}
                                          </SelectItem>
                                        </SelectGroup>
                                      </SelectContent>
                                    </Select>
                                  </Field>
                                </div>

                            <FieldSet className="gap-3">
                              <FieldLegend
                                variant="label"
                                className="mb-0"
                              >
                                {t.imagePositionAndSize}
                              </FieldLegend>
                              <FieldGroup className="gap-3">
                                <FieldGroup className="grid grid-cols-1 gap-3 @min-[360px]/image-card:grid-cols-2">
                                  <TemplateImageNumberField
                                    id={`${fileInputId}-x`}
                                    label={t.imagePositionX}
                                    orientation="horizontal"
                                    min={0}
                                    max={positionXMax}
                                    step={0.5}
                                    value={image.x}
                                    unit="mm"
                                    onChange={(value) =>
                                      updateTemplateImage(image.id, {
                                        x: value,
                                      })
                                    }
                                    disabled={isTemplateReadonly}
                                  />
                                  <TemplateImageNumberField
                                    id={`${fileInputId}-y`}
                                    label={t.imagePositionY}
                                    orientation="horizontal"
                                    min={0}
                                    max={positionYMax}
                                    step={0.5}
                                    value={image.y}
                                    unit="mm"
                                    onChange={(value) =>
                                      updateTemplateImage(image.id, {
                                        y: value,
                                      })
                                    }
                                    disabled={isTemplateReadonly}
                                  />
                                </FieldGroup>

                                <FieldGroup className="grid grid-cols-1 gap-3 @min-[360px]/image-card:grid-cols-2">
                                  <TemplateImageNumberField
                                    id={`${fileInputId}-width`}
                                    label={t.imageWidth}
                                    orientation="horizontal"
                                    min={6}
                                    max={widthMax}
                                    step={0.5}
                                    value={image.width}
                                    unit="mm"
                                    onChange={(value) =>
                                      updateTemplateImage(image.id, {
                                        width: value,
                                      })
                                    }
                                    disabled={isTemplateReadonly}
                                  />
                                  <TemplateImageNumberField
                                    id={`${fileInputId}-height`}
                                    label={t.imageHeight}
                                    orientation="horizontal"
                                    min={6}
                                    max={heightMax}
                                    step={0.5}
                                    value={image.height}
                                    unit="mm"
                                    onChange={(value) =>
                                      updateTemplateImage(image.id, {
                                        height: value,
                                      })
                                    }
                                    disabled={isTemplateReadonly}
                                  />
                                </FieldGroup>
                              </FieldGroup>
                            </FieldSet>

                            <FieldSet className="gap-3">
                              <FieldLegend variant="label" className="mb-0">
                                {t.imageAppearance}
                              </FieldLegend>
                              <FieldGroup className="gap-3">
                                <TemplateImageSliderField
                                  id={`${fileInputId}-opacity`}
                                  label={t.imageOpacity}
                                  min={0.05}
                                  max={1}
                                  step={0.05}
                                  value={image.opacity}
                                  onChange={(value) =>
                                    updateTemplateImage(image.id, {
                                      opacity: value,
                                    })
                                  }
                                  disabled={isTemplateReadonly}
                                />
                                <FieldGroup className="grid grid-cols-1 gap-3 @min-[360px]/image-card:grid-cols-2">
                                  <TemplateImageNumberField
                                    id={`${fileInputId}-border-radius`}
                                    label={t.imageBorderRadius}
                                    orientation="horizontal"
                                    min={0}
                                    max={32}
                                    step={1}
                                    value={image.borderRadius}
                                    unit="px"
                                    onChange={(value) =>
                                      updateTemplateImage(image.id, {
                                        borderRadius: value,
                                      })
                                    }
                                    disabled={isTemplateReadonly}
                                  />
                                  {hasImageBorder ? (
                                    <TemplateImageNumberField
                                      id={`${fileInputId}-border-width`}
                                      label={t.imageBorderWidth}
                                      orientation="horizontal"
                                      min={0.5}
                                      max={8}
                                      step={0.5}
                                      value={image.borderWidth}
                                      unit="px"
                                      onChange={(value) =>
                                        updateTemplateImage(image.id, {
                                          borderWidth: value,
                                        })
                                      }
                                      disabled={isTemplateReadonly}
                                    />
                                  ) : null}
                                </FieldGroup>
                                <FieldGroup className="grid grid-cols-1 gap-3 @min-[360px]/image-card:grid-cols-2">
                                  <Field orientation="horizontal">
                                    <FieldTitle className="text-xs">
                                      {t.imageBorder}
                                    </FieldTitle>
                                    <Button
                                      type="button"
                                      role="switch"
                                      variant="ghost"
                                      size="sm"
                                      data-state={
                                        hasImageBorder
                                          ? "checked"
                                          : "unchecked"
                                      }
                                      aria-label={t.imageBorder}
                                      aria-checked={hasImageBorder}
                                      className={cn(
                                        "group ml-auto h-6 w-11 justify-start rounded-full p-0 shadow-none transition-colors",
                                        hasImageBorder
                                          ? "bg-primary hover:bg-primary/90"
                                          : "bg-muted-foreground/30 hover:bg-muted-foreground/40",
                                      )}
                                      onClick={() =>
                                        updateTemplateImage(image.id, {
                                          borderWidth: hasImageBorder ? 0 : 1,
                                        })
                                      }
                                      disabled={isTemplateReadonly}
                                    >
                                      <span
                                        aria-hidden="true"
                                        className="ml-0.5 size-5 rounded-full bg-background shadow-xs transition-transform group-data-[state=checked]:translate-x-5"
                                      />
                                    </Button>
                                  </Field>
                                  {hasImageBorder ? (
                                    <TemplateImageColorField
                                      id={`${fileInputId}-border-color`}
                                      label={t.imageBorderColor}
                                      value={image.borderColor}
                                      onChange={(value) =>
                                        updateTemplateImage(image.id, {
                                          borderColor: value,
                                        })
                                      }
                                      disabled={isTemplateReadonly}
                                    />
                                  ) : null}
                                </FieldGroup>
                              </FieldGroup>
                            </FieldSet>
                              </FieldGroup>
                            </CollapsibleContent>
                          </Collapsible>
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
