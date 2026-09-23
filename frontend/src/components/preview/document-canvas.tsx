import type { TemplateImageGeometry } from "@/lib/template-image-geometry";
import {
  forwardRef,
  memo,
  useCallback,
  useEffect,
  useImperativeHandle,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { ResumePreview } from "@/components/preview/resume-preview";
import {
  type ResumeDraftReviewPresentation,
  useResumeDraftReviewInteraction,
} from "@/components/preview/resume-draft-review-popover";
import {
  DOCUMENT_CANVAS_MAX_SCALE,
  DOCUMENT_CANVAS_MIN_SCALE,
} from "@/components/preview/document-canvas-model";
import { useDocumentCanvas } from "@/components/preview/use-document-canvas";
import { Button } from "@/components/ui/button";
import type { AppMessages } from "@/i18n";
import type {
  ResumeData,
  ResumeDraftDiff,
  ResumeTemplateDefinition,
  ResumeTypographySettings,
} from "@/types/resume";

export interface DocumentCanvasHandle {
  measurePageCount: (
    signal: AbortSignal,
    measurementKey?: object,
  ) => Promise<number>;
}

interface DocumentCanvasBaseProps {
  className?: string;
  documentT: AppMessages;
  measurementKey?: object;
  onPaginationReadyChange?: (ready: boolean) => void;
  resume: ResumeData;
  t: AppMessages;
  template: ResumeTemplateDefinition;
  toolbarTrailing?: ReactNode;
}

type CanvasControl = [
  label: string,
  text: string,
  nextScale: number | null,
  disabled?: boolean,
  pressed?: boolean,
];

type DocumentCanvasProps =
  | (DocumentCanvasBaseProps & {
      draftReview?: ResumeDraftReviewPresentation;
      diffs?: ResumeDraftDiff[];
      typography: ResumeTypographySettings;
      variant: "resume";
    })
  | (DocumentCanvasBaseProps & {
      onChangeTemplateImage?: (
        imageId: string,
        patch: TemplateImageGeometry,
      ) => void;
      variant: "template";
    });

function measureCanvasPageCount(
  element: HTMLElement | null,
  signal: AbortSignal,
  isCurrent: () => boolean,
) {
  return new Promise<number>((resolve, reject) => {
    let frame = 0;
    const abort = () => {
      cancelAnimationFrame(frame);
      signal.removeEventListener("abort", abort);
      reject(new DOMException("Preview measurement cancelled", "AbortError"));
    };
    const measure = () => {
      if (signal.aborted || !element?.isConnected) {
        abort();
      } else if (
        isCurrent() &&
        element.dataset.resumePaginationReady === "true"
      ) {
        signal.removeEventListener("abort", abort);
        resolve(Number(element.dataset.resumePageCount));
      } else {
        frame = requestAnimationFrame(measure);
      }
    };
    if (signal.aborted) {
      abort();
      return;
    }
    signal.addEventListener("abort", abort, { once: true });
    frame = requestAnimationFrame(measure);
  });
}

export const DocumentCanvas = memo(
  forwardRef<DocumentCanvasHandle, DocumentCanvasProps>(
    function DocumentCanvas(props, ref) {
      const previewRef = useRef<HTMLElement | null>(null);
      const committedMeasurementKey = useRef(props.measurementKey);
      useLayoutEffect(() => {
        committedMeasurementKey.current = props.measurementKey;
      }, [props.measurementKey]);
      const [pageCount, setPageCount] = useState(1);
      const {
        currentPage,
        isFitToWidth,
        onBlur: onViewportBlur,
        onClick,
        onKeyDown,
        onPointer,
        onScroll,
        scale,
        setScale,
        viewportRef,
      } = useDocumentCanvas();
      const { onPaginationReadyChange, t, template } = props;
      const handlePaginationReadyChange = useCallback(
        (ready: boolean, total: number) => {
          setPageCount(total);
          onPaginationReadyChange?.(ready);
        },
        [onPaginationReadyChange],
      );

      useImperativeHandle(
        ref,
        () => ({
          measurePageCount: (signal, measurementKey) =>
            measureCanvasPageCount(
              previewRef.current,
              signal,
              () => committedMeasurementKey.current === measurementKey,
            ),
        }),
        [],
      );

      useEffect(
        () => () => onPaginationReadyChange?.(false),
        [onPaginationReadyChange],
      );

      const isTemplatePreview = props.variant === "template";
      const draftReviewInteraction = useResumeDraftReviewInteraction({
        diffs: !isTemplatePreview ? props.diffs : undefined,
        presentation: !isTemplatePreview ? props.draftReview : undefined,
        previewRef,
        t,
      });
      const typography = isTemplatePreview
        ? template.typography
        : props.typography;
      const fitToWidth = t.fitToWidth;
      const canvasPage = t.canvasPage
        .replace("{current}", String(Math.min(currentPage, pageCount)))
        .replace("{total}", String(pageCount));
      const canvasControls: CanvasControl[] = [
        [t.zoomOut, "−", scale - 0.1, scale <= DOCUMENT_CANVAS_MIN_SCALE],
        [t.actualSize, `${Math.round(scale * 100)}%`, 1],
        [t.zoomIn, "+", scale + 0.1, scale >= DOCUMENT_CANVAS_MAX_SCALE],
        [fitToWidth, fitToWidth, null, false, isFitToWidth],
      ];

      return (
        <section
          className={
            props.className ??
            "resume-preview-card relative flex min-h-0 min-w-0 flex-col overflow-hidden rounded-(--radius-preview) border bg-card"
          }
          onKeyDown={onKeyDown}
        >
          <div
            ref={viewportRef}
            data-slot="document-canvas-viewport"
            tabIndex={0}
            role="region"
            aria-label={t.preview}
            className="document-canvas-viewport min-h-0 flex-1 cursor-default overflow-auto outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
            onAuxClick={onClick}
            onClick={onClick}
            onClickCapture={draftReviewInteraction.onClick}
            onBlur={(event) => {
              onViewportBlur(event);
              draftReviewInteraction.onBlur(event);
            }}
            onFocus={draftReviewInteraction.onFocus}
            onLostPointerCapture={onPointer}
            onPointerDown={onPointer}
            onPointerMove={onPointer}
            onPointerOut={draftReviewInteraction.onPointerOut}
            onPointerOver={draftReviewInteraction.onPointerOver}
            onKeyDownCapture={draftReviewInteraction.onKeyDown}
            onScroll={onScroll}
          >
            <div className="document-canvas-stage flex min-h-full w-max min-w-full items-start justify-center p-6 pb-20">
              <div
                data-document-canvas-paper
                className="document-canvas-scale-content my-auto w-[210mm] shrink-0 cursor-default [&_a]:cursor-default"
              >
                <ResumePreview
                  ref={previewRef}
                  t={props.documentT}
                  resume={props.resume}
                  fontFamily={typography.fontFamily}
                  fontSize={typography.fontSize}
                  template={template}
                  diffs={!isTemplatePreview ? props.diffs : undefined}
                  editableTemplateImages={
                    isTemplatePreview &&
                    !template.isBuiltIn &&
                    Boolean(props.onChangeTemplateImage)
                  }
                  showEmptyTemplateImagePlaceholders={isTemplatePreview}
                  onPaginationReadyChange={handlePaginationReadyChange}
                  onChangeTemplateImage={
                    isTemplatePreview ? props.onChangeTemplateImage : undefined
                  }
                />
              </div>
            </div>
          </div>

          {draftReviewInteraction.popover}

          <div className="absolute bottom-4 left-1/2 z-20 -translate-x-1/2 print:hidden">
            <div className="relative">
              <div
                data-slot="document-canvas-controls"
                className="flex cursor-default items-center gap-1 rounded-md border bg-background/95 p-1 shadow-lg"
              >
                <span
                  data-slot="document-canvas-page"
                  className="whitespace-nowrap px-3 text-center text-xs text-muted-foreground"
                >
                  {canvasPage}
                </span>
                {canvasControls.map(
                  ([label, text, nextScale, disabled, pressed]) => (
                    <Button
                      key={label}
                      size="xs"
                      variant="ghost"
                      className="min-w-8 cursor-default px-2.5 tabular-nums aria-pressed:bg-accent aria-pressed:text-accent-foreground"
                      aria-label={label}
                      aria-pressed={pressed}
                      disabled={disabled}
                      onClick={() => setScale(nextScale)}
                    >
                      {text}
                    </Button>
                  ),
                )}
              </div>
              {props.toolbarTrailing ? (
                <div className="absolute left-full top-0 ml-2">
                  {props.toolbarTrailing}
                </div>
              ) : null}
            </div>
          </div>
        </section>
      );
    },
  ),
);
