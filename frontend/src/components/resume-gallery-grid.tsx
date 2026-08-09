import { memo } from "react";

import { Empty, EmptyDescription } from "@/components/ui/empty";
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
  totalResumeCount,
  templates,
  isSelecting,
  selectedIdSet,
  selectedCount,
  updatedAtFormatter,
  onOpenResume,
  onRequestDelete,
  onToggleSelected,
}: {
  t: AppMessages;
  resumes: ResumeWorkspaceItem[];
  totalResumeCount: number;
  templates: ResumeTemplateDefinition[];
  isSelecting: boolean;
  selectedIdSet: Set<string>;
  selectedCount: number;
  updatedAtFormatter: Intl.DateTimeFormat;
  onOpenResume: (resumeId: string) => void;
  onRequestDelete: (resumeIds: string[]) => void;
  onToggleSelected: (resumeId: string) => void;
}) {
  if (resumes.length === 0) {
    return (
      <Empty className="col-span-full min-h-[390px] border border-border/70 bg-card/55">
        <EmptyDescription className="font-medium">
          {totalResumeCount === 0 ? t.emptyResumes : t.emptyResumeSearch}
        </EmptyDescription>
      </Empty>
    );
  }

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
        showDeleteAction={isSelecting && isSelected && selectedCount === 1}
        updatedAtFormatter={updatedAtFormatter}
        onOpenResume={onOpenResume}
        onRequestDelete={onRequestDelete}
        onToggleSelected={onToggleSelected}
      />
    );
  });
});
