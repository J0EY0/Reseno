import type { ForwardedRef, RefObject } from "react";

import {
  ResumePageContent,
  StandardResumeContent,
} from "@/components/preview/resume-preview-content";
import { TemplateImages } from "@/components/preview/resume-preview-media";
import {
  A4_HEIGHT_MM,
  createResumePageClassName,
  type ResumePreviewModel,
} from "@/components/preview/resume-preview-model";
import type { ResumePaginationState } from "@/components/preview/resume-preview-pagination";
import { cn } from "@/lib/utils";
import type { ResumeTemplateImageElement } from "@/types/resume";

interface PaginatedResumePagesProps {
  editableTemplateImages: boolean;
  forwardedRef: ForwardedRef<HTMLElement>;
  isPaginationReady: boolean;
  measureRef: RefObject<HTMLDivElement | null>;
  model: ResumePreviewModel;
  onMoveTemplateImage?: (
    imageId: string,
    patch: Pick<ResumeTemplateImageElement, "x" | "y">,
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
  onMoveTemplateImage,
  pagination,
  showEmptyTemplateImagePlaceholders,
}: PaginatedResumePagesProps) {
  const pageClassName = createResumePageClassName(model);
  const pageIndexes = Array.from(
    { length: pagination.pageCount },
    (_, index) => index,
  );

  return (
    <section
      ref={forwardedRef}
      className="resume-page-stack"
      data-resume-page-count={pagination.pageCount}
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
          breakBeforeSectionSpacers={pagination.breakBeforeSectionSpacers}
          enableContactLinks
        />
      </div>

      {pageIndexes.map((pageIndex) => (
        <div className="resume-page-shell" key={pageIndex}>
          <p className="resume-page-label print:hidden">
            {`Page ${pageIndex + 1}`}
          </p>
          <article
            data-export-root="resume-page"
            className={cn(pageClassName, "resume-page--content-paged")}
            style={model.pageStyle}
          >
            <TemplateImages
              images={model.layout.images}
              editable={editableTemplateImages}
              showEmptyPlaceholders={
                showEmptyTemplateImagePlaceholders
              }
              onMoveImage={onMoveTemplateImage}
            />
            <div
              className="resume-page-content-viewport"
              style={{
                width: `${model.standardContentWidthMm}mm`,
                height: `${model.standardContentHeightMm}mm`,
              }}
            >
              <div
                className="resume-page-content-flow resume-page-content-fragment"
                style={{
                  ...model.contentFlowStyle,
                  transform: `translateY(-${pageIndex * model.standardContentHeightMm}mm)`,
                }}
              >
                <StandardResumeContent
                  model={model}
                  pageSections={model.fullPreviewSections}
                  breakBeforeSectionSpacers={
                    pagination.breakBeforeSectionSpacers
                  }
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
  onMoveTemplateImage,
  pagination,
  showEmptyTemplateImagePlaceholders,
}: PaginatedResumePagesProps) {
  const pageClassName = createResumePageClassName(model);
  const pageIndexes = Array.from(
    { length: pagination.pageCount },
    (_, index) => index,
  );

  return (
    <section
      ref={forwardedRef}
      className="resume-page-stack"
      data-resume-page-count={pagination.pageCount}
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
          breakBeforeSectionSpacers={pagination.breakBeforeSectionSpacers}
          enableContactLinks
        />
      </div>

      {pageIndexes.map((pageIndex) => (
        <div className="resume-page-shell" key={pageIndex}>
          <p className="resume-page-label print:hidden">
            {`Page ${pageIndex + 1}`}
          </p>
          <article
            data-export-root="resume-page"
            className={cn(pageClassName, "resume-page--paged")}
            style={model.pageStyle}
          >
            <div
              className="resume-page-flow resume-page-fragment resume-page-flow--sidebar"
              style={{
                ...model.pageStyle,
                transform: `translateY(-${pageIndex * A4_HEIGHT_MM}mm)`,
              }}
            >
              <ResumePageContent
                model={model}
                pageSections={model.fullPreviewSections}
                breakBeforeSectionSpacers={
                  pagination.breakBeforeSectionSpacers
                }
                editableTemplateImages={editableTemplateImages}
                showEmptyTemplateImagePlaceholders={
                  showEmptyTemplateImagePlaceholders
                }
                onMoveTemplateImage={onMoveTemplateImage}
                enableContactLinks
              />
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
