import { memo } from "react";

import { Empty, EmptyDescription } from "@/components/ui/empty";
import type { AppMessages } from "@/i18n";
import type {
  ResumeData,
  ResumeTemplateDefinition,
} from "@/types/resume";

import { TemplateGalleryCard } from "./template-gallery-card";

export const TemplateGalleryGrid = memo(function TemplateGalleryGrid({
  t,
  previewResume,
  templates,
  totalTemplateCount,
  defaultTemplateId,
  isSelecting,
  selectedIdSet,
  settingDefaultTemplateId,
  onOpenTemplate,
  onRequestDelete,
  onSetDefaultTemplate,
  onToggleSelected,
}: {
  t: AppMessages;
  previewResume: ResumeData;
  templates: ResumeTemplateDefinition[];
  totalTemplateCount: number;
  defaultTemplateId: string;
  isSelecting: boolean;
  selectedIdSet: Set<string>;
  settingDefaultTemplateId: string | null;
  onOpenTemplate: (templateId: string) => void;
  onRequestDelete: (templateIds: string[]) => void;
  onSetDefaultTemplate: (templateId: string) => void;
  onToggleSelected: (templateId: string) => void;
}) {
  if (templates.length === 0) {
    return (
      <Empty className="col-span-full min-h-[390px] border border-border/70 bg-card/55">
        <EmptyDescription className="font-medium">
          {totalTemplateCount === 0 ? t.emptyTemplates : t.emptyTemplateSearch}
        </EmptyDescription>
      </Empty>
    );
  }

  return templates.map((template) => (
    <TemplateGalleryCard
      key={template.id}
      t={t}
      previewResume={previewResume}
      template={template}
      isDefaultTemplate={defaultTemplateId === template.id}
      isSelecting={isSelecting}
      isSelected={selectedIdSet.has(template.id)}
      settingDefaultTemplateId={settingDefaultTemplateId}
      onOpenTemplate={onOpenTemplate}
      onRequestDelete={onRequestDelete}
      onSetDefaultTemplate={onSetDefaultTemplate}
      onToggleSelected={onToggleSelected}
    />
  ));
});
