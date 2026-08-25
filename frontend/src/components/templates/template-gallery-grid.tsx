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
  settingDefaultTemplateId,
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
  settingDefaultTemplateId: string | null;
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
      settingDefaultTemplateId={settingDefaultTemplateId}
      onOpenTemplate={onOpenTemplate}
      onRequestDelete={onRequestDelete}
      onSetDefaultTemplate={onSetDefaultTemplate}
      onToggleSelected={onToggleSelected}
    />
  ));
});
