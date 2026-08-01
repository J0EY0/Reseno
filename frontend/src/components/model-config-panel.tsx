import { useMemo, useState } from 'react'
import { Bot, Pencil, Trash2 } from 'lucide-react'
import type { ColumnDef } from '@tanstack/react-table'
import { toast } from 'sonner'

import type { AppMessages, Locale } from '@/i18n'
import {
  formatApiKeyPreview,
  getModelDisplayName,
} from '@/lib/model-config'
import { isApiErrorToastShown } from '@/lib/api-client'
import { deleteModelConfig } from '@/lib/model-config-api'
import type { ModelConfig } from '@/types/resume'

import { ConfirmActionDialog } from '@/components/confirm-action-dialog'
import { ModelConfigFormPopover } from '@/components/model-config-form-popover'
import { ModelProviderIcon } from '@/components/model-provider-icon'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { DataTable } from '@/components/data-table'
import {
  Empty,
  EmptyContent,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from '@/components/ui/empty'
import { Spinner } from '@/components/ui/spinner'

export function ModelConfigPanel({
  locale,
  t,
  configs,
  onChange,
}: {
  locale: Locale
  t: AppMessages
  configs: ModelConfig[]
  onChange: (configs: ModelConfig[]) => void
}) {
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null)
  const [deletingModelId, setDeletingModelId] = useState<string | null>(null)
  const contextWindowFormatter = useMemo(
    () => new Intl.NumberFormat(locale === 'zh' ? 'zh-CN' : 'en-US'),
    [locale],
  )

  async function confirmDeleteModel() {
    const modelId = pendingDeleteId

    if (!modelId || deletingModelId) {
      return
    }

    setDeletingModelId(modelId)

    try {
      await deleteModelConfig(modelId)
      onChange(configs.filter((item) => item.id !== modelId))
      toast.success(t.modelConfigDeleted, { closeButton: true })
    } catch (error) {
      console.error('Failed to delete model config.', error)
      if (!isApiErrorToastShown(error)) {
        toast.error(t.modelConfigDeleteFailed, { closeButton: true })
      }
    } finally {
      setDeletingModelId(null)
    }
  }

  const columns = useMemo<ColumnDef<ModelConfig>[]>(
    () => [
      {
        accessorKey: 'model',
        header: t.model,
        cell: ({ row }) => {
          return (
            <div className="flex min-w-[220px] items-center gap-3">
              <ModelProviderIcon
                provider={row.original.iconProvider || row.original.provider}
                size={22}
              />
              <div className="grid min-w-0 gap-1">
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
          )
        },
      },
      {
        accessorKey: 'apiKeyPreview',
        header: () => <span className="block text-center">{t.apiKey}</span>,
        cell: ({ row }) => (
          <div className="flex justify-center">
            <code className="text-xs text-muted-foreground">
              {formatApiKeyPreview(row.original.apiKeyPreview)}
            </code>
          </div>
        ),
      },
      {
        accessorKey: 'contextWindowTokens',
        header: () => <span className="block text-center">{t.contextWindow}</span>,
        cell: ({ row }) => (
          <div className="flex justify-center">
            <span className="font-medium tabular-nums">
              {contextWindowFormatter.format(row.original.contextWindowTokens)}
            </span>
          </div>
        ),
      },
      {
        accessorKey: 'supportsImage',
        header: () => <span className="block text-center">{t.capabilities}</span>,
        cell: ({ row }) => (
          <div className="flex justify-center gap-1">
            {row.original.supportsImage ? (
              <Badge variant="outline">{t.imageInput}</Badge>
            ) : null}
            {row.original.supportsThinking ? (
              <Badge variant="outline">{t.thinking}</Badge>
            ) : null}
            {!row.original.supportsImage && !row.original.supportsThinking ? (
              <span className="text-muted-foreground">—</span>
            ) : null}
          </div>
        ),
      },
      {
        id: 'actions',
        header: () => <span className="block text-center">{t.actions}</span>,
        cell: ({ row }) => (
          <div className="flex items-center justify-center gap-0.5">
            <ModelConfigFormPopover
              t={t}
              locale={locale}
              mode="edit"
              initialConfig={row.original}
              onSubmit={(nextConfig) =>
                onChange(
                  configs.map((item) =>
                    item.id === row.original.id ? nextConfig : item,
                  ),
                )
              }
              trigger={
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="size-8 rounded-md"
                  disabled={deletingModelId !== null}
                >
                  <Pencil className="size-3.5" />
                  <span className="sr-only">{t.editModelConfig}</span>
                </Button>
              }
            />
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="size-8 rounded-md"
              disabled={deletingModelId !== null}
              onClick={() => setPendingDeleteId(row.original.id)}
            >
              {deletingModelId === row.original.id ? (
                <Spinner aria-label={t.deleteModelConfig} />
              ) : (
                <Trash2 className="size-3.5" />
              )}
              <span className="sr-only">{t.deleteModelConfig}</span>
            </Button>
          </div>
        ),
      },
    ],
    [configs, contextWindowFormatter, deletingModelId, locale, onChange, t],
  )

  const addModelAction = (
    <ModelConfigFormPopover
      t={t}
      locale={locale}
      mode="create"
      onSubmit={(nextConfig) => onChange([...configs, nextConfig])}
    />
  )

  return (
    <div className="grid h-[calc(100vh-12rem)] min-h-[420px] gap-4 overflow-hidden">
      <ConfirmActionDialog
        open={pendingDeleteId !== null}
        title={t.deleteModelConfigConfirmTitle}
        description={t.deleteModelConfigConfirmDescription}
        confirmLabel={t.deleteModelConfig}
        cancelLabel={t.cancel}
        onConfirm={() => void confirmDeleteModel()}
        onOpenChange={(open) => {
          if (!open) {
            setPendingDeleteId(null)
          }
        }}
      />

      <Card className="flex min-h-0 flex-col rounded-(--radius-workspace) border-border/80">
        <CardContent className="flex min-h-0 flex-1 flex-col gap-4 overflow-hidden p-6">
          {configs.length === 0 ? (
            <Empty className="min-h-0 rounded-none p-6 md:p-8">
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <Bot />
                </EmptyMedia>
                <EmptyTitle>{t.emptyModelConfigs}</EmptyTitle>
              </EmptyHeader>
              <EmptyContent>{addModelAction}</EmptyContent>
            </Empty>
          ) : (
            <>
              <div className="flex shrink-0 flex-wrap items-center justify-between gap-3">
                <Badge variant="outline">{`${configs.length} ${t.configuredModels}`}</Badge>
                {addModelAction}
              </div>
              <div className="min-h-0 overflow-auto">
                <DataTable
                  columns={columns}
                  data={configs}
                  emptyMessage={t.emptyModelConfigs}
                />
              </div>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
