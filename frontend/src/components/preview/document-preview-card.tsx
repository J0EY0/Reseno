import {
  forwardRef,
  memo,
  useEffect,
  useImperativeHandle,
  useLayoutEffect,
  useRef,
} from "react";

import { ResumePreview } from "@/components/preview/resume-preview";
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
  onPaginationReadyChange?: (ready: boolean) => void;
  resume: ResumeData;
  showPreviewTitle?: boolean;
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
      onMoveTemplateImage?: (
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
      const previewLayoutRef = useRef({
        scale: 1,
        pageHeight: A4_HEIGHT_PX,
      });
      const previewScaleFrameRef = useRef<HTMLDivElement | null>(null);
      const previewScaleBoxRef = useRef<HTMLDivElement | null>(null);
      const previewScaleContentRef = useRef<HTMLDivElement | null>(null);
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

      useLayoutEffect(() => {
        const frameElement = previewScaleFrameRef.current;
        const scaleBoxElement = previewScaleBoxRef.current;
        const scaleContentElement = previewScaleContentRef.current;

        if (!frameElement || !scaleBoxElement || !scaleContentElement) {
          return;
        }

        let animationFrameId: number | null = null;

        const syncPreviewLayout = () => {
          // A detail transition can temporarily detach the preview. Waiting for
          // its real width prevents the replacement from keeping a false shrink.
          if (!frameElement.isConnected) {
            return;
          }

          const frameWidth = frameElement.clientWidth;
          if (frameWidth <= 0) {
            return;
          }

          const availableWidth = Math.max(
            frameWidth - PREVIEW_FRAME_GUTTER_PX,
            frameWidth * 0.88,
          );
          const nextScale = Math.min(1, availableWidth / A4_WIDTH_PX);
          const pageHeight = previewRef.current?.offsetHeight || A4_HEIGHT_PX;
          const currentLayout = previewLayoutRef.current;
          const hasLayoutChange =
            currentLayout.scale !== nextScale ||
            currentLayout.pageHeight !== pageHeight;

          if (!hasLayoutChange) {
            return;
          }

          scaleBoxElement.style.width = `${A4_WIDTH_PX * nextScale}px`;
          scaleBoxElement.style.height = `${pageHeight * nextScale}px`;
          scaleContentElement.style.transform = `scale(${nextScale})`;

          previewLayoutRef.current = { scale: nextScale, pageHeight };
        };

        const schedulePreviewScaleSync = () => {
          if (animationFrameId !== null) {
            return;
          }

          animationFrameId = window.requestAnimationFrame(() => {
            animationFrameId = null;
            syncPreviewLayout();
          });
        };

        syncPreviewLayout();

        const resizeObserver = new ResizeObserver(schedulePreviewScaleSync);
        resizeObserver.observe(frameElement);

        if (previewRef.current) {
          resizeObserver.observe(previewRef.current);
        }

        window.addEventListener("resize", schedulePreviewScaleSync);

        return () => {
          if (animationFrameId !== null) {
            window.cancelAnimationFrame(animationFrameId);
          }
          resizeObserver.disconnect();
          window.removeEventListener("resize", schedulePreviewScaleSync);
        };
      }, []);

      const isTemplatePreview = props.variant === "template";
      const fontFamily = isTemplatePreview
        ? props.template.typography.fontFamily
        : props.typography.fontFamily;
      const fontSize = isTemplatePreview
        ? props.template.typography.fontSize
        : props.typography.fontSize;

      return (
        <section className="resume-preview-card relative flex min-w-0 flex-col overflow-x-hidden rounded-(--radius-preview) border border-border bg-card p-4 print:overflow-visible print:border-0 print:bg-white print:p-0 xl:self-start">
          {props.showPreviewTitle !== false ? (
            <div className="mb-4 print:hidden">
              <p className="text-xs font-medium text-muted-foreground">
                {props.t.previewTitle}
              </p>
            </div>
          ) : null}
          <div
            ref={previewScaleFrameRef}
            className="resume-preview-scale-frame flex min-w-0 justify-center overflow-hidden print:block print:overflow-visible"
          >
            <div
              ref={previewScaleBoxRef}
              className="resume-preview-scale-box relative print:contents"
            >
              <div
                ref={previewScaleContentRef}
                className="resume-preview-scale-content origin-top-left print:contents"
              >
                <ResumePreview
                  ref={previewRef}
                  t={props.t}
                  resume={props.resume}
                  fontFamily={fontFamily}
                  fontSize={fontSize}
                  template={props.template}
                  diffs={props.variant === "resume" ? props.diffs : undefined}
                  editableTemplateImages={
                    props.variant === "template" &&
                    !props.template.isBuiltIn &&
                    Boolean(props.onMoveTemplateImage)
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
        </section>
      );
    },
  ),
);
