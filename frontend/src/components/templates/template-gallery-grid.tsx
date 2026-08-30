import { memo } from "react";

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
  defaultTemplateId,
  isSelecting,
  selectedIdSet,
  openingTemplateId,
  settingDefaultTemplateId,
  onPreloadTemplateDetail,
  onOpenTemplate,
  onRequestDelete,
  onSetDefaultTemplate,
  onToggleSelected,
}: {
  t: AppMessages;
  previewResume: ResumeData;
  templates: ResumeTemplateDefinition[];
  defaultTemplateId: string;
  isSelecting: boolean;
  selectedIdSet: Set<string>;
  openingTemplateId: string | null;
  settingDefaultTemplateId: string | null;
  onPreloadTemplateDetail: () => void;
  onOpenTemplate: (templateId: string) => void;
  onRequestDelete: (templateIds: string[]) => void;
  onSetDefaultTemplate: (templateId: string) => void;
  onToggleSelected: (templateId: string) => void;
}) {
  return templates.map((template) => (
    <TemplateGalleryCard
      key={template.id}
      t={t}
      previewResume={previewResume}
      template={template}
      isDefaultTemplate={defaultTemplateId === template.id}
      isSelecting={isSelecting}
      isSelected={selectedIdSet.has(template.id)}
      isOpening={openingTemplateId === template.id}
      settingDefaultTemplateId={settingDefaultTemplateId}
      onPreloadDetail={onPreloadTemplateDetail}
      onOpenTemplate={onOpenTemplate}
      onRequestDelete={onRequestDelete}
      onSetDefaultTemplate={onSetDefaultTemplate}
      onToggleSelected={onToggleSelected}
    />
  ));
});
