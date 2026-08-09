import { RotateCcw, Trash2 } from "lucide-react";
import type { ReactNode } from "react";

import { ResumeThumbnail } from "@/components/preview/resume-thumbnail";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Empty, EmptyDescription } from "@/components/ui/empty";
import { Spinner } from "@/components/ui/spinner";
import type { AppMessages } from "@/i18n";
import { cn } from "@/lib/utils";
import type {
  ResumeData,
  ResumeTemplateDefinition,
} from "@/types/resume";

export function TrashCountBadge({ count }: { count: number }) {
  return (
    <Badge
      variant="secondary"
      className="h-[18px] min-w-[18px] rounded-full px-1 text-[10px] leading-none text-muted-foreground"
    >
      {count}
    </Badge>
  );
}

export function RecycleBinThumbnail({
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
      {/* Trash thumbnails are visual context only and must never expose editor controls. */}
      <div
        className="pointer-events-none absolute left-0 top-0 origin-top-left scale-[0.084]"
        style={{ width: "210mm", height: "297mm" }}
      >
        <ResumeThumbnail
          t={t}
          resume={resume}
          fontFamily={fontFamily}
          fontSize={fontSize}
          template={template}
          showEmptyTemplateImagePlaceholders={
            showEmptyTemplateImagePlaceholders
          }
        />
      </div>
    </div>
  );
}

export function EmptyTrashState({ children }: { children: string }) {
  return (
    <Empty className="min-h-[128px] p-4 md:p-4">
      <EmptyDescription className="font-medium">{children}</EmptyDescription>
    </Empty>
  );
}

export function TrashSelectionToolbar({
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

export function TrashItemRow({
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
          <p className="mt-1 text-sm text-muted-foreground">{deletedAtText}</p>
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
