import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import type { RecycleBinTab } from "@/components/recycle-bin-types";
import type {
  DeletedResumeTemplateDefinition,
  DeletedResumeWorkspaceItem,
} from "@/types/resume";

// Recycle-bin rows have a stable height, so a fixed size keeps pagination
// predictable without coupling it to viewport measurements.
const TRASH_PAGE_SIZE = 6;

export function useRecycleBinSelection({
  deletedResumes,
  deletedTemplates,
  isActionRunning,
}: {
  deletedResumes: DeletedResumeWorkspaceItem[];
  deletedTemplates: DeletedResumeTemplateDefinition[];
  isActionRunning: () => boolean;
}) {
  const [searchParams, setSearchParams] = useSearchParams();
  const activeTab: RecycleBinTab =
    searchParams.get("tab") === "templates" ? "templates" : "resumes";
  const pageSearchParam = searchParams.get("page");
  const requestedPage = Number(pageSearchParam);
  const hasValidRequestedPage =
    Number.isSafeInteger(requestedPage) && requestedPage > 0;
  const currentPage = hasValidRequestedPage ? requestedPage : 1;
  const [resumeSelection, setResumeSelection] = useState({
    page: currentPage,
    ids: [] as string[],
  });
  const [templateSelection, setTemplateSelection] = useState({
    page: currentPage,
    ids: [] as string[],
  });

  const deletedResumeIdSet = useMemo(
    () => new Set(deletedResumes.map((item) => item.id)),
    [deletedResumes],
  );
  const deletedTemplateIdSet = useMemo(
    () => new Set(deletedTemplates.map((item) => item.id)),
    [deletedTemplates],
  );
  const resumeTotalPages = Math.max(
    1,
    Math.ceil(deletedResumes.length / TRASH_PAGE_SIZE),
  );
  const templateTotalPages = Math.max(
    1,
    Math.ceil(deletedTemplates.length / TRASH_PAGE_SIZE),
  );
  const activeTotalPages =
    activeTab === "resumes" ? resumeTotalPages : templateTotalPages;
  const safeCurrentPage = Math.min(currentPage, activeTotalPages);
  const pageStart = (safeCurrentPage - 1) * TRASH_PAGE_SIZE;
  const paginatedDeletedResumes =
    activeTab === "resumes"
      ? deletedResumes.slice(pageStart, pageStart + TRASH_PAGE_SIZE)
      : [];
  const paginatedDeletedTemplates =
    activeTab === "templates"
      ? deletedTemplates.slice(pageStart, pageStart + TRASH_PAGE_SIZE)
      : [];
  const currentResumePageIdSet = new Set(
    paginatedDeletedResumes.map((item) => item.id),
  );
  const currentTemplatePageIdSet = new Set(
    paginatedDeletedTemplates.map((item) => item.id),
  );
  // Selection belongs to the page where it was made. This makes URL page
  // correction clear stale selection without a state-setting effect.
  const validSelectedResumeIds =
    resumeSelection.page === safeCurrentPage
      ? resumeSelection.ids.filter((id) => deletedResumeIdSet.has(id))
      : [];
  const validSelectedTemplateIds =
    templateSelection.page === safeCurrentPage
      ? templateSelection.ids.filter((id) => deletedTemplateIdSet.has(id))
      : [];
  const selectedResumePageIds = validSelectedResumeIds.filter((id) =>
    currentResumePageIdSet.has(id),
  );
  const selectedTemplatePageIds = validSelectedTemplateIds.filter((id) =>
    currentTemplatePageIdSet.has(id),
  );

  useEffect(() => {
    const needsPageCorrection =
      (pageSearchParam !== null && !hasValidRequestedPage) ||
      currentPage !== safeCurrentPage;

    if (!needsPageCorrection) {
      return;
    }

    setSearchParams(
      (current) => {
        const next = new URLSearchParams(current);

        if (safeCurrentPage > 1) {
          next.set("page", String(safeCurrentPage));
        } else {
          next.delete("page");
        }

        return next;
      },
      { replace: true },
    );
  }, [
    activeTab,
    currentPage,
    hasValidRequestedPage,
    pageSearchParam,
    safeCurrentPage,
    setSearchParams,
  ]);

  function changeTab(value: string) {
    setSearchParams((current) => {
      const next = new URLSearchParams(current);

      if (value === "templates") {
        next.set("tab", "templates");
      } else {
        next.delete("tab");
      }

      next.delete("page");
      return next;
    });
  }

  function changePage(page: number) {
    if (
      isActionRunning() ||
      page === safeCurrentPage ||
      page < 1 ||
      page > activeTotalPages
    ) {
      return;
    }

    if (activeTab === "resumes") {
      setResumeSelection({ page, ids: [] });
    } else {
      setTemplateSelection({ page, ids: [] });
    }

    setSearchParams((current) => {
      const next = new URLSearchParams(current);

      if (page > 1) {
        next.set("page", String(page));
      } else {
        next.delete("page");
      }

      return next;
    });
  }

  function setSelectedResumeIds(ids: string[]) {
    const selectedIdSet = new Set(ids);
    setResumeSelection({
      page: safeCurrentPage,
      ids: paginatedDeletedResumes
        .filter((item) => selectedIdSet.has(item.id))
        .map((item) => item.id),
    });
  }

  function setSelectedTemplateIds(ids: string[]) {
    const selectedIdSet = new Set(ids);
    setTemplateSelection({
      page: safeCurrentPage,
      ids: paginatedDeletedTemplates
        .filter((item) => selectedIdSet.has(item.id))
        .map((item) => item.id),
    });
  }

  function removeResumeIds(ids: string[]) {
    const removedIdSet = new Set(ids);
    setResumeSelection((current) => ({
      ...current,
      ids: current.ids.filter((id) => !removedIdSet.has(id)),
    }));
  }

  function removeTemplateIds(ids: string[]) {
    const removedIdSet = new Set(ids);
    setTemplateSelection((current) => ({
      ...current,
      ids: current.ids.filter((id) => !removedIdSet.has(id)),
    }));
  }

  return {
    activeTab,
    changeTab,
    currentPage: safeCurrentPage,
    changePage,
    resumeTotalPages,
    templateTotalPages,
    paginatedDeletedResumes,
    paginatedDeletedTemplates,
    selectedResumePageIds,
    selectedTemplatePageIds,
    setSelectedResumeIds,
    setSelectedTemplateIds,
    removeResumeIds,
    removeTemplateIds,
  };
}
