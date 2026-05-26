import { useMemo } from 'react'
import { Pencil, Plus, Trash2, Waypoints } from 'lucide-react'
import type { ColumnDef } from '@tanstack/react-table'

import type { AppMessages, Locale } from '@/i18n'
import {
  formatApiKeyPreview,
  getModelDisplayName,
} from '@/lib/model-config'
import { deleteModelConfig } from '@/lib/model-config-api'
import { getModelProviderMeta } from '@/lib/model-providers'
import type { ModelConfig } from '@/types/resume'

import { ModelConfigFormPopover } from '@/components/model-config-form-popover'
import { ModelProviderIcon } from '@/components/model-provider-icon'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { DataTable } from '@/components/ui/data-table'

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
  const columns = useMemo<ColumnDef<ModelConfig>[]>(
    () => [
      {
        accessorKey: 'model',
        header: t.model,
        cell: ({ row }) => {
          const provider = getModelProviderMeta(row.original.provider)

          return (
            <div className="flex min-w-[220px] items-center gap-3">
              <ModelProviderIcon provider={provider.iconProvider} size={22} />
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
        accessorKey: 'temperature',
        header: () => <span className="block text-center">{t.temperature}</span>,
        cell: ({ row }) => (
          <div className="flex justify-center">
            <span className="font-medium">
              {row.original.temperature.toFixed(1)}
            </span>
          </div>
        ),
      },
      {
        accessorKey: 'topP',
        header: () => <span className="block text-center">{t.topP}</span>,
        cell: ({ row }) => (
          <div className="flex justify-center">
            <span className="font-medium">
              {row.original.topP.toFixed(2)}
            </span>
          </div>
        ),
      },
      {
        accessorKey: 'maxTokens',
        header: () => <span className="block text-center">{t.maxTokens}</span>,
        cell: ({ row }) => (
          <div className="flex justify-center">
            <span className="font-medium tabular-nums">
              {typeof row.original.maxTokens === 'number'
                ? row.original.maxTokens
                : '—'}
            </span>
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
                <Button type="button" variant="ghost" size="icon" className="size-8 rounded-md">
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
              onClick={() => {
                void deleteModelConfig(row.original.id)
                  .then(() =>
                    onChange(
                      configs.filter((item) => item.id !== row.original.id),
                    ),
                  )
                  .catch((error) => {
                    console.error('Failed to delete model config.', error)
                  })
              }}
            >
              <Trash2 className="size-3.5" />
              <span className="sr-only">{t.deleteModelConfig}</span>
            </Button>
          </div>
        ),
      },
    ],
    [configs, locale, onChange, t],
  )

  return (
    <div className="grid h-[calc(100vh-12rem)] min-h-[420px] gap-4 overflow-hidden">
      <Card className="flex min-h-0 flex-col rounded-2xl border-border/80">
        <CardHeader className="relative shrink-0 items-center gap-4 text-center">
          <div className="flex size-12 items-center justify-center rounded-2xl border border-border bg-muted">
            <Waypoints className="size-5" />
          </div>
          <div className="space-y-1.5">
            <CardTitle>{t.configuredModels}</CardTitle>
            <CardDescription>{t.modelsHint}</CardDescription>
          </div>
          <ModelConfigFormPopover
            t={t}
            locale={locale}
            mode="create"
            onSubmit={(nextConfig) => onChange([...configs, nextConfig])}
            trigger={
              <Button type="button" className="gap-2 sm:absolute sm:right-6 sm:top-6">
                <Plus className="size-4" />
                {t.addModelConfig}
              </Button>
            }
          />
        </CardHeader>
        <CardContent className="flex min-h-0 flex-1 flex-col space-y-4 overflow-hidden">
          <div className="flex shrink-0 flex-wrap items-center gap-2">
            <Badge variant="outline">{`${configs.length} ${t.configuredModels}`}</Badge>
          </div>
          <div className="min-h-0 overflow-auto">
            <DataTable
              columns={columns}
              data={configs}
              emptyMessage={t.emptyModelConfigs}
            />
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
