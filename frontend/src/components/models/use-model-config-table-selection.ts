import { useEffect, useState } from 'react'
import type { OnChangeFn, RowSelectionState } from '@tanstack/react-table'

import { useGalleryUrlState } from '@/components/use-gallery-url-state'
import type { ModelConfig } from '@/types/resume'

export const MODEL_CONFIG_PAGE_SIZE = 10

interface ModelConfigPageSelection {
  page: number
  ids: string[]
}

export function resolveSelectedModelIds(
  selection: ModelConfigPageSelection,
  currentPage: number,
  pageConfigs: ModelConfig[],
) {
  if (selection.page !== currentPage) {
    return []
  }

  const pageIdSet = new Set(pageConfigs.map((config) => config.id))
  return selection.ids.filter((id) => pageIdSet.has(id))
}

export function useModelConfigTableSelection(configs: ModelConfig[]) {
  const { currentPage, setCurrentPage } = useGalleryUrlState()
  const totalPages = Math.max(
    1,
    Math.ceil(configs.length / MODEL_CONFIG_PAGE_SIZE),
  )
  const safeCurrentPage = Math.min(currentPage, totalPages)
  const pageStart = (safeCurrentPage - 1) * MODEL_CONFIG_PAGE_SIZE
  const pageConfigs = configs.slice(
    pageStart,
    pageStart + MODEL_CONFIG_PAGE_SIZE,
  )
  const [selection, setSelection] = useState<ModelConfigPageSelection>(() => ({
    page: safeCurrentPage,
    ids: [],
  }))
  const pageChanged = selection.page !== safeCurrentPage

  useEffect(() => {
    if (pageChanged) {
      // Browser Back/Forward changes the URL outside this hook's event path.
      // The selectedIds gate below hides stale rows until stored state converges.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setSelection({ page: safeCurrentPage, ids: [] })
    }
  }, [pageChanged, safeCurrentPage])

  const selectedIds = pageChanged
    ? []
    : resolveSelectedModelIds(selection, safeCurrentPage, pageConfigs)
  const rowSelection = Object.fromEntries(
    selectedIds.map((id) => [id, true]),
  )

  const onRowSelectionChange: OnChangeFn<RowSelectionState> = (updater) => {
    setSelection((current) => {
      const currentRowSelection = Object.fromEntries(
        resolveSelectedModelIds(current, safeCurrentPage, pageConfigs).map(
          (id) => [id, true],
        ),
      )
      const nextRowSelection =
        typeof updater === 'function'
          ? updater(currentRowSelection)
          : updater

      return {
        page: safeCurrentPage,
        ids: pageConfigs
          .filter((config) => nextRowSelection[config.id])
          .map((config) => config.id),
      }
    })
  }

  function changePage(page: number) {
    setSelection({ page, ids: [] })
    setCurrentPage(page)
  }

  function removeIds(ids: string[]) {
    const removedIdSet = new Set(ids)
    setSelection((current) => ({
      ...current,
      ids: current.ids.filter((id) => !removedIdSet.has(id)),
    }))
  }

  function clearSelection() {
    setSelection({ page: safeCurrentPage, ids: [] })
  }

  return {
    currentPage: safeCurrentPage,
    totalPages,
    pageConfigs,
    selectedIds,
    rowSelection,
    onRowSelectionChange,
    changePage,
    removeIds,
    clearSelection,
  }
}
