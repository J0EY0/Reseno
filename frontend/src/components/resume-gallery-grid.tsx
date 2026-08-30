import { memo } from "react";

import type { AppMessages } from "@/i18n";
import { getTemplateById } from "@/lib/templates";
import type {
  ResumeTemplateDefinition,
  ResumeWorkspaceItem,
} from "@/types/resume";

import { ResumeGalleryCard } from "./resume-gallery-card";

export const ResumeGalleryGrid = memo(function ResumeGalleryGrid({
  t,
  resumes,
  templates,
  isSelecting,
  selectedIdSet,
  selectedCount,
  openingResumeId,
  updatedAtFormatter,
  onPreloadResumeDetail,
  onOpenResume,
  onRequestDelete,
  onToggleSelected,
}: {
  t: AppMessages;
  resumes: ResumeWorkspaceItem[];
  templates: ResumeTemplateDefinition[];
  isSelecting: boolean;
  selectedIdSet: Set<string>;
  selectedCount: number;
  openingResumeId: string | null;
  updatedAtFormatter: Intl.DateTimeFormat;
  onPreloadResumeDetail: () => void;
  onOpenResume: (resumeId: string) => void;
  onRequestDelete: (resumeIds: string[]) => void;
  onToggleSelected: (resumeId: string) => void;
}) {
  return resumes.map((item) => {
    const isSelected = selectedIdSet.has(item.id);
    return (
      <ResumeGalleryCard
        key={item.id}
        t={t}
        item={item}
        template={getTemplateById(templates, item.template)}
        isSelecting={isSelecting}
        isSelected={isSelected}
        isOpening={openingResumeId === item.id}
        showDeleteAction={isSelecting && isSelected && selectedCount === 1}
        updatedAtFormatter={updatedAtFormatter}
        onPreloadDetail={onPreloadResumeDetail}
        onOpenResume={onOpenResume}
        onRequestDelete={onRequestDelete}
        onToggleSelected={onToggleSelected}
      />
    );
  });
});
