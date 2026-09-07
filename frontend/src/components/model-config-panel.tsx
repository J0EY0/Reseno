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
  onChange: (update: (current: ModelConfig[]) => ModelConfig[]) => ModelConfig[]
}) {
  const [pendingDeleteModelConfigId, setPendingDeleteModelConfigId] = useState<
    string | null
  >(null)
  const [deletingModelConfigId, setDeletingModelConfigId] = useState<
    string | null
  >(null)
  const [pendingBulkDeleteModelConfigIds, setPendingBulkDeleteModelConfigIds] =
    useState<string[]>([])
  const [isBulkDeleting, setIsBulkDeleting] = useState(false)
  const [enteringModelConfigId, setEnteringModelConfigId] = useState<
    string | null
  >(null)
  const [editDialog, setEditDialog] = useState<{
    config: ModelConfig
    returnFocus: HTMLButtonElement | null
    session: number
  } | null>(null)
  const selection = useModelConfigTableSelection(configs)
  const isDeleting = deletingModelConfigId !== null || isBulkDeleting
  const modelConfigIdSet = new Set(configs.map((config) => config.id))
  const pendingBulkModelConfigIds = pendingBulkDeleteModelConfigIds.filter(
    (id) => modelConfigIdSet.has(id),
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

  async function confirmDeleteModelConfig() {
    const modelConfigId = pendingDeleteModelConfigId

    if (!modelConfigId || isDeleting) {
      return
    }

    setDeletingModelConfigId(modelConfigId)

    try {
      await deleteModelConfig(modelConfigId)
      const nextConfigs = onChange((current) =>
        current.filter((item) => item.id !== modelConfigId),
      )
      const nextTotalPages = Math.max(
        1,
        Math.ceil(nextConfigs.length / MODEL_CONFIG_PAGE_SIZE),
      )

      selection.removeModelConfigIds([modelConfigId])
      if (selection.currentPage > nextTotalPages) {
        selection.changePage(nextTotalPages)
      }

      toast.success(t.modelConfigDeleted, { closeButton: true })
    } catch (error) {
      console.error('Failed to delete model config.', error)
      if (!isApiErrorToastShown(error)) {
        toast.error(t.modelConfigDeleteFailed, { closeButton: true })
      }
    } finally {
      setDeletingModelConfigId(null)
    }
  }

  async function confirmBulkDeleteModelConfigs() {
    const modelConfigIds = pendingBulkModelConfigIds

    if (modelConfigIds.length === 0 || isDeleting) {
      setPendingBulkDeleteModelConfigIds([])
      return
    }

    setIsBulkDeleting(true)

    try {
      const response = await deleteModelConfigs(modelConfigIds)
      const deletedModelConfigIdSet = new Set(response.ids)
      const nextConfigs = onChange((current) =>
        current.filter((item) => !deletedModelConfigIdSet.has(item.id)),
      )
      const nextTotalPages = Math.max(
        1,
        Math.ceil(nextConfigs.length / MODEL_CONFIG_PAGE_SIZE),
      )

      selection.clearSelection()
      if (selection.currentPage > nextTotalPages) {
        selection.changePage(nextTotalPages)
      }

      setPendingBulkDeleteModelConfigIds([])
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
        open={pendingDeleteModelConfigId !== null}
        title={t.deleteModelConfigConfirmTitle}
        description={t.deleteModelConfigConfirmDescription}
        confirmLabel={t.deleteModelConfig}
        cancelLabel={t.cancel}
        onConfirm={() => void confirmDeleteModelConfig()}
        onOpenChange={(open) => {
          if (!open) {
            setPendingDeleteModelConfigId(null)
          }
        }}
      />

      <ConfirmActionDialog
        open={pendingBulkModelConfigIds.length > 0}
        title={t.deleteModelConfigsConfirmTitle}
        description={t.deleteModelConfigsConfirmDescription}
        confirmLabel={t.bulkDelete}
        cancelLabel={t.cancel}
        onConfirm={confirmBulkDeleteModelConfigs}
        isPending={isBulkDeleting}
        deferClose
        onOpenChange={(open) => {
          if (!open && !isBulkDeleting) {
            setPendingBulkDeleteModelConfigIds([])
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
            onChange((current) =>
              current.map((item) =>
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
                selectedCount={selection.selectedModelConfigIds.length}
                disabled={isDeleting}
                isPending={isBulkDeleting}
                onDelete={() =>
                  setPendingBulkDeleteModelConfigIds([
                    ...selection.selectedModelConfigIds,
                  ])
                }
              />
              <ModelConfigFormPopover
                t={t}
                locale={locale}
                mode="create"
                onSubmit={(nextConfig) => {
                  const nextConfigs = onChange((current) => [...current, nextConfig])
                  setEnteringModelConfigId(nextConfig.id)
                  selection.changePage(
                    Math.ceil(nextConfigs.length / MODEL_CONFIG_PAGE_SIZE),
                  )
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
                deletingModelConfigId={deletingModelConfigId}
                enteringModelConfigId={enteringModelConfigId}
                disabled={isDeleting}
                onDelete={setPendingDeleteModelConfigId}
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
