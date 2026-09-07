import { useCallback, useDeferredValue, useMemo, useState } from "react";

import { useGalleryUrlState } from "@/components/use-gallery-url-state";
import type { ResumeTemplateDefinition } from "@/types/resume";

function matchesTemplateQuery(
  query: string,
  item: Pick<ResumeTemplateDefinition, "name" | "description">,
) {
  if (!query) {
    return true;
  }
  return `${item.name} ${item.description}`.toLowerCase().includes(query);
}

export function useTemplateGalleryController({
  templates,
  pageSize,
  onDeleteTemplates,
}: {
  templates: ResumeTemplateDefinition[];
  pageSize: number;
  onDeleteTemplates: (templateIds: string[]) => Promise<string[]>;
}) {
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [isSelecting, setIsSelecting] = useState(false);
  const [pendingDeleteIds, setPendingDeleteIds] = useState<string[]>([]);
  const [isDeleteDialogOpen, setIsDeleteDialogOpen] = useState(false);
  const { currentPage, searchQuery, setCurrentPage, setSearchQuery } =
    useGalleryUrlState();
  const deferredSearchQuery = useDeferredValue(searchQuery);
  const customTemplateIdSet = useMemo(
    () =>
      new Set(
        templates.filter((item) => !item.isBuiltIn).map((item) => item.id),
      ),
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
  const totalPages = Math.max(1, Math.ceil(visibleTemplates.length / pageSize));
  const safeCurrentPage = Math.min(currentPage, totalPages);
  const paginatedTemplates = visibleTemplates.slice(
    (safeCurrentPage - 1) * pageSize,
    safeCurrentPage * pageSize,
  );

  const toggleSelected = useCallback(
    (templateId: string) => {
      if (!customTemplateIdSet.has(templateId)) {
        return;
      }
      setSelectedIds((current) =>
        current.includes(templateId)
          ? current.filter((id) => id !== templateId)
          : [...current, templateId],
      );
    },
    [customTemplateIdSet],
  );
  const toggleSelecting = useCallback(() => {
    setIsSelecting((current) => {
      if (current) {
        setSelectedIds([]);
      }
      return !current;
    });
  }, []);
  const requestDelete = useCallback(
    (templateIds: string[]) => {
      const customTemplateIds = templateIds.filter((id) =>
        customTemplateIdSet.has(id),
      );
      if (customTemplateIds.length === 0) {
        return;
      }
      setPendingDeleteIds(customTemplateIds);
      setIsDeleteDialogOpen(true);
    },
    [customTemplateIdSet],
  );
  const confirmDelete = useCallback(async () => {
    const deleted = onDeleteTemplates(pendingDeleteIds);
    setPendingDeleteIds([]);
    setIsDeleteDialogOpen(false);
    const deletedIds = new Set(await deleted);
    setSelectedIds((current) => current.filter((id) => !deletedIds.has(id)));
  }, [onDeleteTemplates, pendingDeleteIds]);
  const setDeleteDialogOpen = useCallback((nextOpen: boolean) => {
    setIsDeleteDialogOpen(nextOpen);
    if (!nextOpen) {
      setPendingDeleteIds([]);
    }
  }, []);

  return {
    confirmDelete,
    isDeleteDialogOpen,
    isSelecting,
    paginatedTemplates,
    pendingDeleteIds,
    requestDelete,
    safeCurrentPage,
    searchQuery,
    selectedIdSet,
    selectedTemplateIds,
    setCurrentPage,
    setDeleteDialogOpen,
    setSearchQuery,
    toggleSelected,
    toggleSelecting,
    totalPages,
  };
}
