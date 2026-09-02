import type {
  ColumnDef,
  OnChangeFn,
  RowSelectionState,
} from "@tanstack/react-table";
import { EllipsisVertical, RotateCcw, Trash2 } from "lucide-react";
import { useCallback, useMemo, type ReactNode } from "react";

import { DataTable } from "@/components/data-table";
import { ResumeThumbnail } from "@/components/preview/resume-thumbnail";
import type { RecycleBinPreviewTarget } from "@/components/recycle-bin-types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Empty, EmptyDescription } from "@/components/ui/empty";
import { Spinner } from "@/components/ui/spinner";
import type { AppMessages } from "@/i18n";
import { useLocalizedMessages } from "@/i18n/use-localized-messages";
import { cn } from "@/lib/utils";
import type {
  DocumentLocale,
  ResumeData,
  ResumeTemplateDefinition,
} from "@/types/resume";

export interface RecycleBinTableItem {
  id: string;
  thumbnail: ReactNode;
  title: string;
  subtitle: string;
  deletedAtText: string;
  isRestoring: boolean;
  previewTarget: RecycleBinPreviewTarget;
}

export function TrashCountBadge({ count }: { count: number }) {
  return (
    <Badge
      variant="secondary"
      className="h-[18px] min-w-[18px] rounded-full px-1 text-[10px] leading-none text-muted-foreground transition-colors duration-200 group-data-[state=inactive]/trash-tab:bg-background"
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
  documentLocale,
  showEmptyTemplateImagePlaceholders = false,
}: {
  t: AppMessages;
  resume: ResumeData;
  template: ResumeTemplateDefinition;
  fontFamily: ResumeTemplateDefinition["typography"]["fontFamily"];
  fontSize: number;
  documentLocale?: DocumentLocale;
  showEmptyTemplateImagePlaceholders?: boolean;
}) {
  const documentMessages = useLocalizedMessages(documentLocale ?? null);
  const previewMessages = documentLocale ? documentMessages : t;

  return (
    <div
      aria-hidden="true"
      className="relative h-[68px] w-12 shrink-0 overflow-hidden rounded-md border border-zinc-200 bg-white shadow-sm"
    >
      {/* Trash thumbnails are visual context only and must never expose editor controls. */}
      {previewMessages ? (
        <div
          className="pointer-events-none absolute left-0 top-0 origin-top-left scale-[0.0605]"
          style={{ width: "210mm", height: "297mm" }}
        >
          <ResumeThumbnail
            t={previewMessages}
            resume={resume}
            fontFamily={fontFamily}
            fontSize={fontSize}
            template={template}
            showEmptyTemplateImagePlaceholders={
              showEmptyTemplateImagePlaceholders
            }
          />
        </div>
      ) : null}
    </div>
  );
}

export function EmptyTrashState({ children }: { children: string }) {
  return (
    <Empty className="min-h-[390px] p-4 md:p-4">
      <EmptyDescription className="font-medium">{children}</EmptyDescription>
    </Empty>
  );
}

export function TrashBulkActions({
  restoreLabel,
  deleteLabel,
  selectedCount,
  onRestore,
  onDelete,
  isRestoring,
  disabled,
}: {
  restoreLabel: string;
  deleteLabel: string;
  selectedCount: number;
  onRestore: () => void;
  onDelete: () => void;
  isRestoring: boolean;
  disabled: boolean;
}) {
  const canBulkAction = selectedCount >= 2;

  return (
    <div className="ml-auto flex min-w-0">
      <div
        data-slot="trash-bulk-actions"
        data-state={canBulkAction ? "open" : "closed"}
        aria-hidden={!canBulkAction}
        inert={!canBulkAction}
        className={cn(
          "grid min-w-0 transition-all duration-150 ease-out",
          !canBulkAction && "pointer-events-none",
        )}
        style={{
          gridTemplateColumns: canBulkAction ? "1fr" : "0fr",
          opacity: canBulkAction ? 1 : 0,
          transform: canBulkAction
            ? "translateX(0) scale(1)"
            : "translateX(0.25rem) scale(0.98)",
          transformOrigin: "right center",
        }}
      >
        <div className="flex min-w-0 gap-2 overflow-hidden">
          <Button
            type="button"
            variant="outline"
            size="default"
            tabIndex={canBulkAction ? undefined : -1}
            disabled={disabled || !canBulkAction}
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
            size="default"
            tabIndex={canBulkAction ? undefined : -1}
            disabled={disabled || !canBulkAction}
            onClick={onDelete}
          >
            <Trash2 data-icon="inline-start" />
            {deleteLabel}
          </Button>
        </div>
      </div>
    </div>
  );
}

function RecycleBinRowActions({
  item,
  previewLabel,
  restoreLabel,
  deleteLabel,
  actionsLabel,
  disabled,
  onPreview,
  onRestore,
  onDelete,
}: {
  item: RecycleBinTableItem;
  previewLabel: string;
  restoreLabel: string;
  deleteLabel: string;
  actionsLabel: string;
  disabled: boolean;
  onPreview: (target: RecycleBinPreviewTarget, triggerId: string) => void;
  onRestore: (itemId: string) => void;
  onDelete: (itemId: string) => void;
}) {
  return (
    <div className="flex items-center justify-end">
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            className="text-muted-foreground data-[state=open]:bg-muted"
            disabled={disabled}
            data-trash-action-trigger={item.id}
            aria-label={`${actionsLabel}: ${item.title}`}
            title={actionsLabel}
          >
            {item.isRestoring ? (
              <Spinner aria-label={restoreLabel} />
            ) : (
              <EllipsisVertical />
            )}
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent
          align="end"
          className="w-32 whitespace-nowrap"
        >
          <DropdownMenuGroup>
            <DropdownMenuItem
              onSelect={() => onPreview(item.previewTarget, item.id)}
            >
              {previewLabel}
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => onRestore(item.id)}>
              {restoreLabel}
            </DropdownMenuItem>
          </DropdownMenuGroup>
          <DropdownMenuSeparator />
          <DropdownMenuGroup>
            <DropdownMenuItem
              variant="destructive"
              onSelect={() => onDelete(item.id)}
            >
              {deleteLabel}
            </DropdownMenuItem>
          </DropdownMenuGroup>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}

export function RecycleBinTable({
  items,
  selectedIds,
  itemLabel,
  deletedAtLabel,
  selectAllLabel,
  selectLabel,
  previewLabel,
  restoreLabel,
  deleteLabel,
  actionsLabel,
  emptyMessage,
  disabled,
  onPreview,
  onSelectionChange,
  onRestore,
  onDelete,
}: {
  items: RecycleBinTableItem[];
  selectedIds: string[];
  itemLabel: string;
  deletedAtLabel: string;
  selectAllLabel: string;
  selectLabel: string;
  previewLabel: string;
  restoreLabel: string;
  deleteLabel: string;
  actionsLabel: string;
  emptyMessage: string;
  disabled: boolean;
  onPreview: (target: RecycleBinPreviewTarget, triggerId: string) => void;
  onSelectionChange: (itemIds: string[]) => void;
  onRestore: (itemId: string) => void;
  onDelete: (itemId: string) => void;
}) {
  const rowSelection = useMemo<RowSelectionState>(
    () => Object.fromEntries(selectedIds.map((id) => [id, true])),
    [selectedIds],
  );
  const handleRowSelectionChange = useCallback<
    OnChangeFn<RowSelectionState>
  >(
    (updater) => {
      const nextSelection =
        typeof updater === "function" ? updater(rowSelection) : updater;
      onSelectionChange(
        items
          .filter((item) => nextSelection[item.id])
          .map((item) => item.id),
      );
    },
    [items, onSelectionChange, rowSelection],
  );
  const columns = useMemo<ColumnDef<RecycleBinTableItem>[]>(
    () => [
      {
        id: "select",
        header: ({ table }) => (
          <Checkbox
            checked={
              table.getIsAllPageRowsSelected()
                ? true
                : table.getIsSomePageRowsSelected()
                  ? "indeterminate"
                  : false
            }
            disabled={disabled}
            aria-label={selectAllLabel}
            onCheckedChange={(checked) =>
              table.toggleAllPageRowsSelected(checked === true)
            }
          />
        ),
        cell: ({ row }) => (
          <Checkbox
            checked={row.getIsSelected()}
            disabled={disabled}
            aria-label={`${selectLabel}: ${row.original.title}`}
            onCheckedChange={(checked) =>
              row.toggleSelected(checked === true)
            }
          />
        ),
        enableHiding: false,
        enableSorting: false,
      },
      {
        id: "item",
        header: () => <span className="block pl-[60px]">{itemLabel}</span>,
        cell: ({ row }) => (
          <div className="flex min-w-72 items-center gap-3">
            {row.original.thumbnail}
            <div className="grid min-w-0 gap-0.5 leading-5">
              <span
                className="truncate font-medium text-foreground"
                title={row.original.title}
              >
                {row.original.title}
              </span>
              {row.original.subtitle ? (
                <span
                  className="truncate text-xs text-muted-foreground"
                  title={row.original.subtitle}
                >
                  {row.original.subtitle}
                </span>
              ) : null}
            </div>
          </div>
        ),
      },
      {
        id: "deletedAt",
        header: () => (
          <span className="block min-w-36 text-center">{deletedAtLabel}</span>
        ),
        cell: ({ row }) => (
          <span className="block min-w-36 text-center text-muted-foreground tabular-nums">
            {row.original.deletedAtText}
          </span>
        ),
      },
      {
        id: "actions",
        header: () => <span className="sr-only">{actionsLabel}</span>,
        cell: ({ row }) => (
          <RecycleBinRowActions
            item={row.original}
            previewLabel={previewLabel}
            restoreLabel={restoreLabel}
            deleteLabel={deleteLabel}
            actionsLabel={actionsLabel}
            disabled={disabled}
            onPreview={onPreview}
            onRestore={onRestore}
            onDelete={onDelete}
          />
        ),
      },
    ],
    [
      actionsLabel,
      deleteLabel,
      deletedAtLabel,
      disabled,
      itemLabel,
      onDelete,
      onPreview,
      onRestore,
      previewLabel,
      restoreLabel,
      selectAllLabel,
      selectLabel,
    ],
  );

  return (
    <div data-slot="trash-table">
      <DataTable
        columns={columns}
        data={items}
        emptyMessage={emptyMessage}
        tableClassName="min-w-[640px]"
        getRowId={(item) => item.id}
        enableRowSelection
        rowSelection={rowSelection}
        onRowSelectionChange={handleRowSelectionChange}
      />
    </div>
  );
}
