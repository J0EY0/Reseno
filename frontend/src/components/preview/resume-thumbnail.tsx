import { memo } from "react";

import { ResumePageContent } from "@/components/preview/resume-preview-content";
import {
  createResumePageClassName,
  useResumePreviewModel,
} from "@/components/preview/resume-preview-model";
import type { AppMessages } from "@/i18n";
import type {
  ResumeData,
  ResumeFontFamily,
  ResumeTemplateDefinition,
} from "@/types/resume";

interface ResumeThumbnailProps {
  fontFamily: ResumeFontFamily;
  fontSize: number;
  resume: ResumeData;
  showEmptyTemplateImagePlaceholders?: boolean;
  t: AppMessages;
  template: ResumeTemplateDefinition;
}

export const ResumeThumbnail = memo(function ResumeThumbnail({
  fontFamily,
  fontSize,
  resume,
  showEmptyTemplateImagePlaceholders = false,
  t,
  template,
}: ResumeThumbnailProps) {
  const model = useResumePreviewModel({
    fontFamily,
    fontSize,
    resume,
    t,
    template,
  });

  return (
    <article
      data-export-root="resume-page"
      className={createResumePageClassName(model, true)}
      style={model.pageStyle}
    >
      <ResumePageContent
        model={model}
        pageSections={model.fullPreviewSections}
        showEmptyTemplateImagePlaceholders={showEmptyTemplateImagePlaceholders}
        enableContactLinks={false}
      />
    </article>
  );
});
