import type { TemplateImageGeometry } from "@/lib/template-image-geometry";
import type { ForwardedRef, RefObject } from "react";

import {
  ResumePageContent,
  StandardResumeContent,
} from "@/components/preview/resume-preview-content";
import { TemplateImages } from "@/components/preview/resume-preview-media";
import {
  createResumePageClassName,
  type ResumePreviewModel,
} from "@/components/preview/resume-preview-model";
import type { ResumePaginationState } from "@/components/preview/resume-preview-pagination";
import { cn } from "@/lib/utils";

interface PaginatedResumePagesProps {
  editableTemplateImages: boolean;
  forwardedRef: ForwardedRef<HTMLElement>;
  isPaginationReady: boolean;
  measureRef: RefObject<HTMLDivElement | null>;
  model: ResumePreviewModel;
  onChangeTemplateImage?: (
    imageId: string,
    patch: TemplateImageGeometry,
  ) => void;
  pagination: ResumePaginationState;
  showEmptyTemplateImagePlaceholders: boolean;
}

function StandardPaginatedResume({
  editableTemplateImages,
  forwardedRef,
  isPaginationReady,
  measureRef,
  model,
  onChangeTemplateImage,
  pagination,
  showEmptyTemplateImagePlaceholders,
}: PaginatedResumePagesProps) {
  const pageClassName = createResumePageClassName(model);

  return (
    <section
      ref={forwardedRef}
      className="resume-page-stack"
      data-resume-page-count={pagination.pages.length}
      data-resume-pagination-ready={isPaginationReady ? "true" : "false"}
    >
      <div
        ref={measureRef}
        className="resume-page-content-flow resume-page-content-flow--measure"
        style={model.contentFlowStyle}
        aria-hidden="true"
        inert
      >
        <StandardResumeContent
          model={model}
          pageSections={model.fullPreviewSections}
          enableContactLinks
        />
      </div>

      {pagination.pages.map((page) => (
        <div className="resume-page-shell" key={page.startOffsetMm}>
          <article
            data-export-root="resume-page"
            className={cn(pageClassName, "resume-page--content-paged")}
            style={model.pageStyle}
          >
            <TemplateImages
              images={model.layout.images}
              editable={editableTemplateImages}
              showEmptyPlaceholders={showEmptyTemplateImagePlaceholders}
              onChangeImage={onChangeTemplateImage}
            />
            <div
              className="resume-page-content-viewport"
              style={{
                width: `${model.standardContentWidthMm}mm`,
                height: `${page.visibleHeightMm}mm`,
              }}
            >
              <div
                className="resume-page-content-flow resume-page-content-fragment"
                style={{
                  ...model.contentFlowStyle,
                  transform: `translateY(-${page.startOffsetMm}mm)`,
                }}
              >
                <StandardResumeContent
                  model={model}
                  pageSections={model.fullPreviewSections}
                  enableContactLinks
                />
              </div>
            </div>
          </article>
        </div>
      ))}
    </section>
  );
}

function SidebarPaginatedResume({
  editableTemplateImages,
  forwardedRef,
  isPaginationReady,
  measureRef,
  model,
  onChangeTemplateImage,
  pagination,
  showEmptyTemplateImagePlaceholders,
}: PaginatedResumePagesProps) {
  const pageClassName = createResumePageClassName(model);

  return (
    <section
      ref={forwardedRef}
      className="resume-page-stack"
      data-resume-page-count={pagination.pages.length}
      data-resume-pagination-ready={isPaginationReady ? "true" : "false"}
    >
      <div
        ref={measureRef}
        className="resume-page-flow resume-page-flow--measure resume-page-flow--sidebar"
        style={model.pageStyle}
        aria-hidden="true"
        inert
      >
        <ResumePageContent
          model={model}
          pageSections={model.fullPreviewSections}
          enableContactLinks
        />
      </div>

      {pagination.pages.map((page) => (
        <div className="resume-page-shell" key={page.startOffsetMm}>
          <article
            data-export-root="resume-page"
            className={cn(pageClassName, "resume-page--paged")}
            style={model.pageStyle}
          >
            <div
              className="resume-page-flow-viewport"
              style={{ height: `${page.visibleHeightMm}mm` }}
            >
              <div
                className="resume-page-flow resume-page-fragment resume-page-flow--sidebar"
                style={{
                  ...model.pageStyle,
                  transform: `translateY(-${page.startOffsetMm}mm)`,
                }}
              >
                <ResumePageContent
                  model={model}
                  pageSections={model.fullPreviewSections}
                  editableTemplateImages={editableTemplateImages}
                  showEmptyTemplateImagePlaceholders={
                    showEmptyTemplateImagePlaceholders
                  }
                  onChangeTemplateImage={onChangeTemplateImage}
                  enableContactLinks
                />
              </div>
            </div>
          </article>
        </div>
      ))}
    </section>
  );
}

export function PaginatedResumePages(props: PaginatedResumePagesProps) {
  return props.model.isSidebarLayout ? (
    <SidebarPaginatedResume {...props} />
  ) : (
    <StandardPaginatedResume {...props} />
  );
}
