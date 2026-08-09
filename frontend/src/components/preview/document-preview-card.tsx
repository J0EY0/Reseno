import {
  forwardRef,
  memo,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";

import { ResumePreview } from "@/components/preview/resume-preview";
import { ViewTransitionBoundary } from "@/components/view-transition";
import type { AppMessages } from "@/i18n";
import type {
  ResumeData,
  ResumeDraftDiff,
  ResumeTemplateDefinition,
  ResumeTemplateImageElement,
  ResumeTypographySettings,
} from "@/types/resume";

const A4_WIDTH_PX = (210 / 25.4) * 96;
const A4_HEIGHT_PX = (297 / 25.4) * 96;
const PREVIEW_FRAME_GUTTER_PX = 48;

export interface DocumentPreviewHandle {
  measurePageCount: () => Promise<number>;
}

interface DocumentPreviewBaseProps {
  id: string;
  onPaginationReadyChange?: (ready: boolean) => void;
  resume: ResumeData;
  t: AppMessages;
  template: ResumeTemplateDefinition;
}

type DocumentPreviewCardProps =
  | (DocumentPreviewBaseProps & {
      diffs?: ResumeDraftDiff[];
      typography: ResumeTypographySettings;
      variant: "resume";
    })
  | (DocumentPreviewBaseProps & {
      onMoveTemplateImage: (
        imageId: string,
        patch: Pick<ResumeTemplateImageElement, "x" | "y">,
      ) => void;
      variant: "template";
    });

async function measurePreviewPageCount(element: HTMLElement | null) {
  let remainingFrames = 8;

  // ResumePreview paginates after layout. The fitting strategy must measure the
  // committed candidate instead of duplicating the preview's pagination rules.
  await new Promise<void>((resolve) => {
    const tick = () => {
      remainingFrames -= 1;
      if (remainingFrames <= 0) {
        resolve();
        return;
      }
      window.requestAnimationFrame(tick);
    };

    window.requestAnimationFrame(tick);
  });

  const rawPageCount = element?.dataset.resumePageCount;
  const pageCount = rawPageCount ? Number(rawPageCount) : 1;

  return Number.isFinite(pageCount) && pageCount > 0 ? pageCount : 1;
}

export const DocumentPreviewCard = memo(
  forwardRef<DocumentPreviewHandle, DocumentPreviewCardProps>(
    function DocumentPreviewCard(props, ref) {
      const [previewScale, setPreviewScale] = useState(1);
      const [previewPageHeight, setPreviewPageHeight] =
        useState(A4_HEIGHT_PX);
      const previewScaleFrameRef = useRef<HTMLDivElement | null>(null);
      const previewRef = useRef<HTMLElement | null>(null);
      const { onPaginationReadyChange } = props;

      useImperativeHandle(
        ref,
        () => ({
          measurePageCount: () => measurePreviewPageCount(previewRef.current),
        }),
        [],
      );

      useEffect(
        () => () => onPaginationReadyChange?.(false),
        [onPaginationReadyChange],
      );

      useEffect(() => {
        const frameElement = previewScaleFrameRef.current;

        if (!frameElement) {
          return;
        }

        let animationFrameId = 0;

        const syncPreviewScale = () => {
          // A detail transition can temporarily detach the preview. Waiting for
          // its real width prevents the replacement from keeping a false shrink.
          if (!frameElement.isConnected || frameElement.clientWidth <= 0) {
            return;
          }

          const frameWidth = frameElement.clientWidth;
          const availableWidth = Math.max(
            frameWidth - PREVIEW_FRAME_GUTTER_PX,
            frameWidth * 0.88,
          );
          const nextScale = Math.min(1, availableWidth / A4_WIDTH_PX);
          const pageHeight = previewRef.current?.offsetHeight || A4_HEIGHT_PX;

          setPreviewScale(nextScale);
          setPreviewPageHeight(pageHeight);
        };

        const syncPreviewScaleDuringLayoutTransition = () => {
          window.cancelAnimationFrame(animationFrameId);

          let remainingFrames = 24;
          const tick = () => {
            syncPreviewScale();
            remainingFrames -= 1;

            if (remainingFrames > 0) {
              animationFrameId = window.requestAnimationFrame(tick);
            }
          };

          animationFrameId = window.requestAnimationFrame(tick);
        };

        syncPreviewScale();
        syncPreviewScaleDuringLayoutTransition();

        const resizeObserver = new ResizeObserver(
          syncPreviewScaleDuringLayoutTransition,
        );
        resizeObserver.observe(frameElement);

        if (previewRef.current) {
          resizeObserver.observe(previewRef.current);
        }

        window.addEventListener("resize", syncPreviewScaleDuringLayoutTransition);

        return () => {
          window.cancelAnimationFrame(animationFrameId);
          resizeObserver.disconnect();
          window.removeEventListener(
            "resize",
            syncPreviewScaleDuringLayoutTransition,
          );
        };
      }, []);

      const isTemplatePreview = props.variant === "template";
      const scaledPreviewWidth = A4_WIDTH_PX * previewScale;
      const scaledPreviewHeight = previewPageHeight * previewScale;
      const previewTransitionName = `${props.variant}-preview-${props.id}`;
      const fontFamily = isTemplatePreview
        ? props.template.typography.fontFamily
        : props.typography.fontFamily;
      const fontSize = isTemplatePreview
        ? props.template.typography.fontSize
        : props.typography.fontSize;

      return (
        <section className="resume-preview-card relative flex min-w-0 flex-col overflow-x-hidden rounded-(--radius-preview) border border-border bg-card p-4 print:overflow-visible print:border-0 print:bg-white print:p-0 xl:self-start">
          <div className="mb-4 print:hidden">
            <p className="text-xs font-medium text-muted-foreground">
              {props.t.previewTitle}
            </p>
          </div>
          <ViewTransitionBoundary
            name={previewTransitionName}
            share="morph"
            default="none"
          >
            <div
              ref={previewScaleFrameRef}
              className="resume-preview-scale-frame flex min-w-0 justify-center overflow-hidden print:block print:overflow-visible"
            >
              <div
                className="resume-preview-scale-box relative print:contents"
                style={{
                  width: scaledPreviewWidth,
                  height: scaledPreviewHeight,
                }}
              >
                <div
                  className="resume-preview-scale-content origin-top-left print:contents"
                  style={{
                    width: "210mm",
                    transform: `scale(${previewScale})`,
                  }}
                >
                  <ResumePreview
                    ref={previewRef}
                    t={props.t}
                    resume={props.resume}
                    fontFamily={fontFamily}
                    fontSize={fontSize}
                    template={props.template}
                    diffs={
                      props.variant === "resume" ? props.diffs : undefined
                    }
                    editableTemplateImages={
                      isTemplatePreview && !props.template.isBuiltIn
                    }
                    showEmptyTemplateImagePlaceholders={isTemplatePreview}
                    onPaginationReadyChange={onPaginationReadyChange}
                    onMoveTemplateImage={
                      props.variant === "template"
                        ? props.onMoveTemplateImage
                        : undefined
                    }
                  />
                </div>
              </div>
            </div>
          </ViewTransitionBoundary>
        </section>
      );
    },
  ),
);
