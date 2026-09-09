import { useEffect, useState } from "react";
import type { OnChangeFn, RowSelectionState } from "@tanstack/react-table";

import { useGalleryUrlState } from "@/components/use-gallery-url-state";
import type { ModelConfig } from "@/types/resume";

export const MODEL_CONFIG_PAGE_SIZE = 10;

interface ModelConfigPageSelection {
  page: number;
  modelConfigIds: string[];
}

export function resolveSelectedModelConfigIds(
  selection: ModelConfigPageSelection,
  currentPage: number,
  pageConfigs: ModelConfig[],
) {
  if (selection.page !== currentPage) {
    return [];
  }

  const pageIdSet = new Set(pageConfigs.map((config) => config.id));
  return selection.modelConfigIds.filter((id) => pageIdSet.has(id));
}

export function useModelConfigTableSelection(configs: ModelConfig[]) {
  const { currentPage, setCurrentPage } = useGalleryUrlState();
  const totalPages = Math.max(
    1,
    Math.ceil(configs.length / MODEL_CONFIG_PAGE_SIZE),
  );
  const safeCurrentPage = Math.min(currentPage, totalPages);
  const pageStart = (safeCurrentPage - 1) * MODEL_CONFIG_PAGE_SIZE;
  const pageConfigs = configs.slice(
    pageStart,
    pageStart + MODEL_CONFIG_PAGE_SIZE,
  );
  const [selection, setSelection] = useState<ModelConfigPageSelection>(() => ({
    page: safeCurrentPage,
    modelConfigIds: [],
  }));
  const pageChanged = selection.page !== safeCurrentPage;

  useEffect(() => {
    if (pageChanged) {
      // Browser Back/Forward changes the URL outside this hook's event path.
      // The selectedModelConfigIds gate below hides stale rows until stored
      // state converges.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setSelection({ page: safeCurrentPage, modelConfigIds: [] });
    }
  }, [pageChanged, safeCurrentPage]);

  const selectedModelConfigIds = pageChanged
    ? []
    : resolveSelectedModelConfigIds(selection, safeCurrentPage, pageConfigs);
  const rowSelection = Object.fromEntries(
    selectedModelConfigIds.map((id) => [id, true]),
  );

  const onRowSelectionChange: OnChangeFn<RowSelectionState> = (updater) => {
    setSelection((current) => {
      const currentRowSelection = Object.fromEntries(
        resolveSelectedModelConfigIds(
          current,
          safeCurrentPage,
          pageConfigs,
        ).map((id) => [id, true]),
      );
      const nextRowSelection =
        typeof updater === "function" ? updater(currentRowSelection) : updater;

      return {
        page: safeCurrentPage,
        modelConfigIds: pageConfigs
          .filter((config) => nextRowSelection[config.id])
          .map((config) => config.id),
      };
    });
  };

  function changePage(page: number) {
    setSelection({ page, modelConfigIds: [] });
    setCurrentPage(page);
  }

  function removeModelConfigIds(modelConfigIds: string[]) {
    const removedModelConfigIdSet = new Set(modelConfigIds);
    setSelection((current) => ({
      ...current,
      modelConfigIds: current.modelConfigIds.filter(
        (id) => !removedModelConfigIdSet.has(id),
      ),
    }));
  }

  function clearSelection() {
    setSelection({ page: safeCurrentPage, modelConfigIds: [] });
  }

  return {
    currentPage: safeCurrentPage,
    totalPages,
    pageConfigs,
    selectedModelConfigIds,
    rowSelection,
    onRowSelectionChange,
    changePage,
    removeModelConfigIds,
    clearSelection,
  };
}
