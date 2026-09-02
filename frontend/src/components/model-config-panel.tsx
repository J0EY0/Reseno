import { useCallback, useState } from 'react'
import { toast } from 'sonner'

import type { AppMessages, Locale } from '@/i18n'
import { isApiErrorToastShown } from '@/lib/api-client'
import {
  deleteModelConfig,
  deleteModelConfigs,
} from '@/lib/model-config-api'
import type { ModelConfig } from '@/types/resume'

import { ConfirmActionDialog } from '@/components/confirm-action-dialog'
import { GalleryPagination } from '@/components/gallery-pagination'
import { ModelConfigFormPopover } from '@/components/model-config-form-popover'
import { ModelConfigBulkDeleteAction } from '@/components/models/model-config-bulk-delete-action'
import { ModelConfigTable } from '@/components/models/model-config-table'
import {
  MODEL_CONFIG_PAGE_SIZE,
  useModelConfigTableSelection,
} from '@/components/models/use-model-config-table-selection'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { Empty, EmptyDescription } from '@/components/ui/empty'

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
  const [pendingBulkDeleteIds, setPendingBulkDeleteIds] = useState<string[]>([])
  const [isBulkDeleting, setIsBulkDeleting] = useState(false)
  const [enteringModelId, setEnteringModelId] = useState<string | null>(null)
  const [editDialog, setEditDialog] = useState<{
    config: ModelConfig
    returnFocus: HTMLButtonElement | null
    session: number
  } | null>(null)
  const selection = useModelConfigTableSelection(configs)
  const isDeleting = deletingModelId !== null || isBulkDeleting
  const configIdSet = new Set(configs.map((config) => config.id))
  const pendingBulkModelIds = pendingBulkDeleteIds.filter((id) =>
    configIdSet.has(id),
  )
  const openEditDialog = useCallback(
    (config: ModelConfig, returnFocus: HTMLButtonElement | null) => {
      setEditDialog((current) => ({
        config,
        returnFocus,
        session: (current?.session ?? 0) + 1,
      }))
    },
    [],
  )

  async function confirmDeleteModel() {
    const modelId = pendingDeleteId

    if (!modelId || isDeleting) {
      return
    }

    setDeletingModelId(modelId)

    try {
      await deleteModelConfig(modelId)
      const nextConfigs = configs.filter((item) => item.id !== modelId)
      const nextTotalPages = Math.max(
        1,
        Math.ceil(nextConfigs.length / MODEL_CONFIG_PAGE_SIZE),
      )

      selection.removeIds([modelId])
      if (selection.currentPage > nextTotalPages) {
        selection.changePage(nextTotalPages)
      }

      onChange(nextConfigs)
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

  async function confirmBulkDeleteModels() {
    const modelIds = pendingBulkModelIds

    if (modelIds.length === 0 || isDeleting) {
      setPendingBulkDeleteIds([])
      return
    }

    setIsBulkDeleting(true)

    try {
      const response = await deleteModelConfigs(modelIds)
      const deletedIdSet = new Set(response.ids)
      const nextConfigs = configs.filter((item) => !deletedIdSet.has(item.id))
      const nextTotalPages = Math.max(
        1,
        Math.ceil(nextConfigs.length / MODEL_CONFIG_PAGE_SIZE),
      )

      selection.clearSelection()
      if (selection.currentPage > nextTotalPages) {
        selection.changePage(nextTotalPages)
      }

      onChange(nextConfigs)
      setPendingBulkDeleteIds([])
      toast.success(t.modelConfigsDeleted, { closeButton: true })
    } catch (error) {
      console.error('Failed to delete model configs.', error)
      if (!isApiErrorToastShown(error)) {
        toast.error(t.modelConfigsDeleteFailed, { closeButton: true })
      }
    } finally {
      setIsBulkDeleting(false)
    }
  }

  return (
    <div data-slot="model-config-panel" className="grid gap-4">
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

      <ConfirmActionDialog
        open={pendingBulkModelIds.length > 0}
        title={t.deleteModelConfigsConfirmTitle}
        description={t.deleteModelConfigsConfirmDescription}
        confirmLabel={t.bulkDelete}
        cancelLabel={t.cancel}
        onConfirm={confirmBulkDeleteModels}
        isPending={isBulkDeleting}
        deferClose
        onOpenChange={(open) => {
          if (!open && !isBulkDeleting) {
            setPendingBulkDeleteIds([])
          }
        }}
      />

      {editDialog ? (
        <ModelConfigFormPopover
          key={editDialog.session}
          t={t}
          locale={locale}
          mode="edit"
          defaultOpen
          initialConfig={editDialog.config}
          trigger={null}
          restoreFocus={() => editDialog.returnFocus?.focus()}
          onSubmit={(nextConfig) =>
            onChange(
              configs.map((item) =>
                item.id === editDialog.config.id ? nextConfig : item,
              ),
            )
          }
        />
      ) : null}

      <Card className="min-w-0 rounded-(--radius-workspace) border-border/80 bg-muted/35 shadow-none py-0">
        <CardContent className="grid min-w-0 gap-4 p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <Badge variant="outline">{`${configs.length} ${t.configuredModels}`}</Badge>
            <div className="ml-auto flex items-center gap-2">
              <ModelConfigBulkDeleteAction
                label={t.bulkDelete}
                selectedCount={selection.selectedIds.length}
                disabled={isDeleting}
                isPending={isBulkDeleting}
                onDelete={() =>
                  setPendingBulkDeleteIds([...selection.selectedIds])
                }
              />
              <ModelConfigFormPopover
                t={t}
                locale={locale}
                mode="create"
                onSubmit={(nextConfig) => {
                  const nextConfigs = [...configs, nextConfig]
                  setEnteringModelId(nextConfig.id)
                  selection.changePage(
                    Math.ceil(nextConfigs.length / MODEL_CONFIG_PAGE_SIZE),
                  )
                  onChange(nextConfigs)
                }}
              />
            </div>
          </div>
          <div
            data-slot="model-config-content"
            className="flex min-h-[390px] min-w-0 flex-col gap-4"
          >
            {configs.length === 0 ? (
              <Empty className="min-h-[390px] rounded-none p-6 md:p-8">
                <EmptyDescription className="font-medium">
                  {t.emptyModelConfigs}
                </EmptyDescription>
              </Empty>
            ) : (
              <ModelConfigTable
                locale={locale}
                t={t}
                configs={selection.pageConfigs}
                rowSelection={selection.rowSelection}
                onRowSelectionChange={selection.onRowSelectionChange}
                deletingModelId={deletingModelId}
                enteringModelId={enteringModelId}
                disabled={isDeleting}
                onDelete={setPendingDeleteId}
                onEdit={openEditDialog}
              />
            )}
            <GalleryPagination
              currentPage={selection.currentPage}
              totalPages={selection.totalPages}
              t={t}
              onPageChange={selection.changePage}
              disabled={isDeleting}
            />
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
