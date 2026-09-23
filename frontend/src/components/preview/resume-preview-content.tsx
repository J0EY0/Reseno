import type { TemplateImageGeometry } from "@/lib/template-image-geometry";
import { memo } from "react";

import {
  SidebarBasicInfo,
  StandardBasicInfo,
} from "@/components/preview/resume-preview-basic-info";
import { TemplateImages } from "@/components/preview/resume-preview-media";
import type {
  PaginatedResumeSection,
  ResumePreviewModel,
} from "@/components/preview/resume-preview-model";
import { SectionsList } from "@/components/preview/resume-preview-sections";

interface ResumePageContentProps {
  editableTemplateImages?: boolean;
  enableContactLinks: boolean;
  model: ResumePreviewModel;
  onChangeTemplateImage?: (
    imageId: string,
    patch: TemplateImageGeometry,
  ) => void;
  pageSections: PaginatedResumeSection[];
  showEmptyTemplateImagePlaceholders?: boolean;
}

export const StandardResumeContent = memo(function StandardResumeContent({
  enableContactLinks,
  model,
  pageSections,
}: Pick<
  ResumePageContentProps,
  "enableContactLinks" | "model" | "pageSections"
>) {
  return (
    <div className="relative z-10" data-resume-flow-content="true">
      <StandardBasicInfo
        t={model.t}
        basic={model.resume.basic}
        settings={model.settings}
        layout={model.layout}
        basicDiffByField={model.diffLookup.basicDiffByField}
        enableContactLinks={enableContactLinks}
      />
      <SectionsList
        sections={pageSections}
        t={model.t}
        settings={model.settings}
        layout={model.layout}
        isSidebarLayout={false}
        enableContactLinks={enableContactLinks}
        className="mt-[1.25em]"
        sectionDiffById={model.diffLookup.sectionDiffById}
        itemDiffById={model.diffLookup.itemDiffById}
        deletedItemDiffsBySectionId={
          model.diffLookup.deletedItemDiffsBySectionId
        }
        deletedSectionDiffs={model.diffLookup.deletedSectionDiffs}
      />
    </div>
  );
});

export const ResumePageContent = memo(function ResumePageContent({
  editableTemplateImages = false,
  enableContactLinks,
  model,
  onChangeTemplateImage,
  pageSections,
  showEmptyTemplateImagePlaceholders = false,
}: ResumePageContentProps) {
  if (model.isSidebarLayout) {
    return (
      <>
        <TemplateImages
          images={model.layout.images}
          editable={editableTemplateImages}
          showEmptyPlaceholders={showEmptyTemplateImagePlaceholders}
          onChangeImage={onChangeTemplateImage}
        />
        <div
          className="relative z-10 grid min-h-[297mm] grid-cols-[64mm_minmax(0,1fr)]"
          data-resume-flow-content="true"
        >
          <SidebarBasicInfo
            t={model.t}
            basic={model.resume.basic}
            settings={model.settings}
            layout={model.layout}
            basicDiffByField={model.diffLookup.basicDiffByField}
            enableContactLinks={enableContactLinks}
          />
          <div
            className="min-w-0"
            style={{
              padding: `${model.settings.pagePaddingTop}mm ${model.settings.pagePaddingX}mm ${model.settings.pagePaddingBottom}mm`,
              backgroundColor: model.settings.pageBackground,
            }}
          >
            <SectionsList
              sections={pageSections}
              t={model.t}
              settings={model.settings}
              layout={model.layout}
              isSidebarLayout
              enableContactLinks={enableContactLinks}
              sectionDiffById={model.diffLookup.sectionDiffById}
              itemDiffById={model.diffLookup.itemDiffById}
              deletedItemDiffsBySectionId={
                model.diffLookup.deletedItemDiffsBySectionId
              }
              deletedSectionDiffs={model.diffLookup.deletedSectionDiffs}
            />
          </div>
        </div>
      </>
    );
  }

  return (
    <>
      <TemplateImages
        images={model.layout.images}
        editable={editableTemplateImages}
        showEmptyPlaceholders={showEmptyTemplateImagePlaceholders}
        onChangeImage={onChangeTemplateImage}
      />
      <StandardResumeContent
        model={model}
        pageSections={pageSections}
        enableContactLinks={enableContactLinks}
      />
    </>
  );
});
