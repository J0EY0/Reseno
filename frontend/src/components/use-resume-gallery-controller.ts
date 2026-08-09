import { useCallback, useDeferredValue, useMemo, useState } from "react";

import { useGalleryUrlState } from "@/components/use-gallery-url-state";
import type { Locale } from "@/i18n";
import type { ResumeWorkspaceItem } from "@/types/resume";

function matchesResumeQuery(
  query: string,
  item: Pick<ResumeWorkspaceItem, "resume" | "title">,
) {
  if (!query) {
    return true;
  }

  return [
    item.title,
    item.resume.basic.name,
    item.resume.basic.headline,
    item.resume.basic.email,
    item.resume.basic.phone,
  ]
    .join(" ")
    .toLowerCase()
    .includes(query);
}

export function useResumeGalleryController({
  locale,
  resumes,
  pageSize,
  onDeleteResume,
  onBulkDeleteResumes,
}: {
  locale: Locale;
  resumes: ResumeWorkspaceItem[];
  pageSize: number;
  onDeleteResume: (resumeId: string) => void;
  onBulkDeleteResumes: (resumeIds: string[]) => void;
}) {
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [isSelecting, setIsSelecting] = useState(false);
  const [pendingDeleteIds, setPendingDeleteIds] = useState<string[]>([]);
  const [isDeleteDialogOpen, setIsDeleteDialogOpen] = useState(false);
  const { currentPage, searchQuery, setCurrentPage, setSearchQuery } =
    useGalleryUrlState();
  const deferredSearchQuery = useDeferredValue(searchQuery);
  const resumeIdSet = useMemo(
    () => new Set(resumes.map((item) => item.id)),
    [resumes],
  );
  const selectedIdSet = useMemo(() => new Set(selectedIds), [selectedIds]);
  const selectedResumeIds = useMemo(
    () => selectedIds.filter((id) => resumeIdSet.has(id)),
    [resumeIdSet, selectedIds],
  );
  const normalizedQuery = deferredSearchQuery.trim().toLowerCase();
  const visibleResumes = useMemo(
    () => resumes.filter((item) => matchesResumeQuery(normalizedQuery, item)),
    [normalizedQuery, resumes],
  );
  const updatedAtFormatter = useMemo(
    () =>
      new Intl.DateTimeFormat(locale === "zh" ? "zh-CN" : "en-US", {
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      }),
    [locale],
  );
  const totalPages = Math.max(1, Math.ceil(visibleResumes.length / pageSize));
  const safeCurrentPage = Math.min(currentPage, totalPages);
  const paginatedResumes = visibleResumes.slice(
    (safeCurrentPage - 1) * pageSize,
    safeCurrentPage * pageSize,
  );

  const toggleSelected = useCallback((resumeId: string) => {
    setSelectedIds((current) =>
      current.includes(resumeId)
        ? current.filter((id) => id !== resumeId)
        : [...current, resumeId],
    );
  }, []);
  const toggleSelecting = useCallback(() => {
    setIsSelecting((current) => {
      if (current) {
        setSelectedIds([]);
      }
      return !current;
    });
  }, []);
  const requestDelete = useCallback((resumeIds: string[]) => {
    if (resumeIds.length === 0) {
      return;
    }
    setPendingDeleteIds(resumeIds);
    setIsDeleteDialogOpen(true);
  }, []);
  const confirmDelete = useCallback(() => {
    if (pendingDeleteIds.length === 1) {
      onDeleteResume(pendingDeleteIds[0]);
    } else if (pendingDeleteIds.length > 1) {
      const pendingDeleteIdSet = new Set(pendingDeleteIds);
      onBulkDeleteResumes(pendingDeleteIds);
      setSelectedIds((current) =>
        current.filter((id) => !pendingDeleteIdSet.has(id)),
      );
    }
    setPendingDeleteIds([]);
    setIsDeleteDialogOpen(false);
  }, [onBulkDeleteResumes, onDeleteResume, pendingDeleteIds]);
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
    paginatedResumes,
    pendingDeleteIds,
    requestDelete,
    safeCurrentPage,
    searchQuery,
    selectedIdSet,
    selectedResumeIds,
    setCurrentPage,
    setDeleteDialogOpen,
    setSearchQuery,
    toggleSelected,
    toggleSelecting,
    totalPages,
    updatedAtFormatter,
  };
}
