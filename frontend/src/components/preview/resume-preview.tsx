import { forwardRef, memo, useEffect } from "react";

import { useResumeFontReadyToken } from "@/components/preview/resume-font-loader";
import { useResumePreviewModel } from "@/components/preview/resume-preview-model";
import { PaginatedResumePages } from "@/components/preview/resume-preview-pages";
import { useResumePagination } from "@/components/preview/resume-preview-pagination";
import type { AppMessages } from "@/i18n";
import type {
  ResumeData,
  ResumeDraftDiff,
  ResumeFontFamily,
  ResumeTemplateDefinition,
  ResumeTemplateImageElement,
} from "@/types/resume";

interface ResumePreviewProps {
  diffs?: ResumeDraftDiff[];
  editableTemplateImages?: boolean;
  fontFamily: ResumeFontFamily;
  fontSize: number;
  onMoveTemplateImage?: (
    imageId: string,
    patch: Pick<ResumeTemplateImageElement, "x" | "y">,
  ) => void;
  onPaginationReadyChange?: (ready: boolean, pageCount: number) => void;
  resume: ResumeData;
  showEmptyTemplateImagePlaceholders?: boolean;
  t: AppMessages;
  template: ResumeTemplateDefinition;
}

export const ResumePreview = memo(
  forwardRef<HTMLElement, ResumePreviewProps>(function ResumePreview(
    {
      diffs,
      editableTemplateImages = false,
      fontFamily,
      fontSize,
      onMoveTemplateImage,
      onPaginationReadyChange,
      resume,
      showEmptyTemplateImagePlaceholders = false,
      t,
      template,
    },
    ref,
  ) {
    const model = useResumePreviewModel({
      diffs,
      fontFamily,
      fontSize,
      resume,
      t,
      template,
    });
    const resumeFontReadyToken = useResumeFontReadyToken(fontFamily, resume, t);
    const { isPaginationReady, measureRef, pagination } = useResumePagination(
      model,
      resumeFontReadyToken,
    );

    useEffect(() => {
      onPaginationReadyChange?.(
        isPaginationReady,
        pagination.pages.length,
      );
    }, [
      isPaginationReady,
      onPaginationReadyChange,
      pagination.pages.length,
    ]);

    return (
      <PaginatedResumePages
        forwardedRef={ref}
        model={model}
        pagination={pagination}
        measureRef={measureRef}
        isPaginationReady={isPaginationReady}
        editableTemplateImages={editableTemplateImages}
        showEmptyTemplateImagePlaceholders={
          showEmptyTemplateImagePlaceholders
        }
        onMoveTemplateImage={onMoveTemplateImage}
      />
    );
  }),
);
