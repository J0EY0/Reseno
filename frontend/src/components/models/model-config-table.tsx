import { useMemo, useRef } from "react";
import { EllipsisVertical } from "lucide-react";
import type {
  ColumnDef,
  OnChangeFn,
  RowSelectionState,
} from "@tanstack/react-table";

import { DataTable } from "@/components/data-table";
import { ModelProviderIcon } from "@/components/model-provider-icon";
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
import { Spinner } from "@/components/ui/spinner";
import type { AppMessages, Locale } from "@/i18n";
import { formatApiKeyPreview, getModelDisplayName } from "@/lib/model-config";
import type { ModelConfig } from "@/types/resume";

function ModelConfigRowActions({
  config,
  deletingModelConfigId,
  disabled,
  t,
  onDelete,
  onEdit,
}: {
  config: ModelConfig;
  deletingModelConfigId: string | null;
  disabled: boolean;
  t: AppMessages;
  onDelete: (modelConfigId: string) => void;
  onEdit: (config: ModelConfig, returnFocus: HTMLButtonElement | null) => void;
}) {
  const triggerRef = useRef<HTMLButtonElement>(null);

  return (
    <div className="flex items-center justify-end">
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            ref={triggerRef}
            type="button"
            variant="ghost"
            size="icon-sm"
            className="text-muted-foreground data-[state=open]:bg-muted"
            disabled={disabled}
            aria-label={t.actions}
            title={t.actions}
          >
            {deletingModelConfigId === config.id ? (
              <Spinner aria-label={t.deleteModelConfig} />
            ) : (
              <EllipsisVertical />
            )}
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-32">
          <DropdownMenuGroup>
            <DropdownMenuItem
              onSelect={() => onEdit(config, triggerRef.current)}
            >
              {t.editModelConfigAction}
            </DropdownMenuItem>
          </DropdownMenuGroup>
          <DropdownMenuSeparator />
          <DropdownMenuGroup>
            <DropdownMenuItem
              variant="destructive"
              onSelect={() => onDelete(config.id)}
            >
              {t.deleteModelConfigAction}
            </DropdownMenuItem>
          </DropdownMenuGroup>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}

export function ModelConfigTable({
  locale,
  t,
  configs,
  rowSelection,
  onRowSelectionChange,
  deletingModelConfigId,
  enteringModelConfigId,
  disabled,
  onDelete,
  onEdit,
}: {
  locale: Locale;
  t: AppMessages;
  configs: ModelConfig[];
  rowSelection: RowSelectionState;
  onRowSelectionChange: OnChangeFn<RowSelectionState>;
  deletingModelConfigId: string | null;
  enteringModelConfigId: string | null;
  disabled: boolean;
  onDelete: (modelConfigId: string) => void;
  onEdit: (config: ModelConfig, returnFocus: HTMLButtonElement | null) => void;
}) {
  const contextWindowFormatter = useMemo(
    () => new Intl.NumberFormat(locale === "zh" ? "zh-CN" : "en-US"),
    [locale],
  );
  const columns = useMemo<ColumnDef<ModelConfig>[]>(
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
            aria-label={t.selectAll}
            onCheckedChange={(checked) =>
              table.toggleAllPageRowsSelected(checked === true)
            }
          />
        ),
        cell: ({ row }) => (
          <Checkbox
            checked={row.getIsSelected()}
            disabled={disabled}
            aria-label={`${t.selectItems}: ${getModelDisplayName(row.original)}`}
            onCheckedChange={(checked) => row.toggleSelected(checked === true)}
          />
        ),
        enableHiding: false,
        enableSorting: false,
      },
      {
        accessorKey: "model",
        header: () => <span className="block pl-11">{t.model}</span>,
        cell: ({ row }) => (
          <div className="flex min-w-60 items-center gap-3">
            <span className="flex size-8 shrink-0 items-center justify-center">
              <ModelProviderIcon
                provider={row.original.iconProvider || row.original.provider}
                size={18}
              />
            </span>
            <div className="grid min-w-0 leading-4">
              <span
                className="truncate font-medium text-foreground"
                title={getModelDisplayName(row.original)}
              >
                {getModelDisplayName(row.original)}
              </span>
              <span
                className="truncate text-xs text-muted-foreground"
                title={row.original.apiUrl}
              >
                {row.original.apiUrl}
              </span>
            </div>
          </div>
        ),
      },
      {
        accessorKey: "apiKeyPreview",
        header: () => <span className="block min-w-32">{t.apiKey}</span>,
        cell: ({ row }) => (
          <div className="flex min-w-32">
            <code className="text-xs text-muted-foreground">
              {formatApiKeyPreview(row.original.apiKeyPreview)}
            </code>
          </div>
        ),
      },
      {
        accessorKey: "contextWindowTokens",
        header: () => (
          <span className="block min-w-32 pr-2 text-right">
            {t.contextWindow}
          </span>
        ),
        cell: ({ row }) => (
          <div className="flex min-w-32 justify-end pr-2">
            <span className="font-medium tabular-nums">
              {contextWindowFormatter.format(row.original.contextWindowTokens)}
            </span>
          </div>
        ),
      },
      {
        accessorKey: "supportsImage",
        header: () => (
          <span className="flex min-w-52 justify-center">{t.capabilities}</span>
        ),
        cell: ({ row }) => (
          <div className="flex min-w-52 justify-center gap-1.5">
            {row.original.supportsImage ? (
              <Badge variant="outline" className="px-1.5 text-muted-foreground">
                {t.imageInput}
              </Badge>
            ) : null}
            {row.original.supportsThinking ? (
              <Badge variant="outline" className="px-1.5 text-muted-foreground">
                {t.thinking}
              </Badge>
            ) : null}
            {!row.original.supportsImage && !row.original.supportsThinking ? (
              <span className="text-muted-foreground">—</span>
            ) : null}
          </div>
        ),
      },
      {
        id: "actions",
        header: () => <span className="sr-only">{t.actions}</span>,
        cell: ({ row }) => (
          <ModelConfigRowActions
            config={row.original}
            deletingModelConfigId={deletingModelConfigId}
            disabled={disabled}
            t={t}
            onDelete={onDelete}
            onEdit={onEdit}
          />
        ),
      },
    ],
    [
      contextWindowFormatter,
      deletingModelConfigId,
      disabled,
      onDelete,
      onEdit,
      t,
    ],
  );

  return (
    <DataTable
      columns={columns}
      data={configs}
      emptyMessage={t.emptyModelConfigs}
      tableClassName="min-w-[760px]"
      getRowId={(config) => config.id}
      getRowClassName={(config) =>
        config.id === enteringModelConfigId
          ? "animate-in fade-in duration-200 motion-reduce:animate-none"
          : undefined
      }
      enableRowSelection
      rowSelection={rowSelection}
      onRowSelectionChange={onRowSelectionChange}
    />
  );
}
