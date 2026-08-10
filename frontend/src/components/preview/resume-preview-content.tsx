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
import type { ResumeTemplateImageElement } from "@/types/resume";

interface ResumePageContentProps {
  breakBeforeSectionSpacers?: Record<string, number>;
  editableTemplateImages?: boolean;
  enableContactLinks: boolean;
  model: ResumePreviewModel;
  onMoveTemplateImage?: (
    imageId: string,
    patch: Pick<ResumeTemplateImageElement, "x" | "y">,
  ) => void;
  pageSections: PaginatedResumeSection[];
  showEmptyTemplateImagePlaceholders?: boolean;
}

export function StandardResumeContent({
  breakBeforeSectionSpacers,
  enableContactLinks,
  model,
  pageSections,
}: Pick<
  ResumePageContentProps,
  | "breakBeforeSectionSpacers"
  | "enableContactLinks"
  | "model"
  | "pageSections"
>) {
  return (
    <div className="relative z-10" data-resume-flow-content="true">
      <StandardBasicInfo
        t={model.t}
        basic={model.resume.basic}
        settings={model.settings}
        layout={model.layout}
        summaryDiff={model.diffLookup.summaryDiff}
        enableContactLinks={enableContactLinks}
      />
      <SectionsList
        sections={pageSections}
        t={model.t}
        settings={model.settings}
        layout={model.layout}
        isSidebarLayout={false}
        className="mt-7"
        breakBeforeSectionSpacers={breakBeforeSectionSpacers}
        sectionDiffById={model.diffLookup.sectionDiffById}
        itemDiffById={model.diffLookup.itemDiffById}
      />
    </div>
  );
}

export function ResumePageContent({
  breakBeforeSectionSpacers,
  editableTemplateImages = false,
  enableContactLinks,
  model,
  onMoveTemplateImage,
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
          onMoveImage={onMoveTemplateImage}
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
            summaryDiff={model.diffLookup.summaryDiff}
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
              breakBeforeSectionSpacers={breakBeforeSectionSpacers}
              sectionDiffById={model.diffLookup.sectionDiffById}
              itemDiffById={model.diffLookup.itemDiffById}
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
        onMoveImage={onMoveTemplateImage}
      />
      <StandardResumeContent
        model={model}
        pageSections={pageSections}
        breakBeforeSectionSpacers={breakBeforeSectionSpacers}
        enableContactLinks={enableContactLinks}
      />
    </>
  );
}
