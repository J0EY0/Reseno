import {
  useCallback,
  useLayoutEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type PointerEvent,
  type UIEvent,
} from "react";

import {
  clampDocumentCanvasScale,
  getFitWidthScale,
  resolveDocumentCanvasScalePreference,
} from "@/components/preview/document-canvas-model";

type DocumentCanvasZoom = [scale: number, fitToWidth: boolean];
type PanSession = [
  pointerId: number,
  scrollLeft: number,
  scrollTop: number,
  x: number,
  y: number,
];

const DOCUMENT_CANVAS_SCALE_STORAGE_KEY =
  "resumate-document-canvas-scale-v1";

function loadDocumentCanvasScale() {
  if (typeof window === "undefined") {
    return resolveDocumentCanvasScalePreference(null);
  }

  try {
    return resolveDocumentCanvasScalePreference(
      window.localStorage.getItem(DOCUMENT_CANVAS_SCALE_STORAGE_KEY),
    );
  } catch {
    return resolveDocumentCanvasScalePreference(null);
  }
}

function saveDocumentCanvasScale(scale: number) {
  if (typeof window === "undefined") {
    return;
  }

  try {
    window.localStorage.setItem(
      DOCUMENT_CANVAS_SCALE_STORAGE_KEY,
      String(scale),
    );
  } catch {
    return;
  }
}

export function useDocumentCanvas() {
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const [zoom, setZoom] = useState<DocumentCanvasZoom>(() => [
    loadDocumentCanvasScale(),
    false,
  ]);
  const zoomRef = useRef<DocumentCanvasZoom>(zoom);
  const panSessionRef = useRef<PanSession | null>(null);
  const [currentPage, setCurrentPage] = useState(1);
  const onScroll = (event: UIEvent<HTMLDivElement>) => {
    const viewport = event.currentTarget;
    const pages = viewport.querySelectorAll<HTMLElement>(".resume-page-shell");
    const middle =
      viewport.getBoundingClientRect().top + viewport.clientHeight / 2;
    let index = 0;
    while (pages[index]?.getBoundingClientRect().bottom < middle) {
      index += 1;
    }
    setCurrentPage(Math.min(index + 1, pages.length) || 1);
  };

  const setScale = useCallback(
    (
      requestedScale: number | null,
      clientX?: number,
      clientY?: number,
    ) => {
      const viewport = viewportRef.current;
      if (!viewport) {
        return;
      }

      const fitToWidth = requestedScale === null;
      const nextScale =
        requestedScale ?? getFitWidthScale(viewport.clientWidth);
      if (nextScale === null) {
        return;
      }

      const scale = clampDocumentCanvasScale(nextScale);
      const [currentScale, currentlyFitsWidth] = zoomRef.current;
      if (currentScale === scale && currentlyFitsWidth === fitToWidth) {
        return;
      }

      const viewportBounds = viewport.getBoundingClientRect();
      clientX ??= viewportBounds.left + viewportBounds.width / 2;
      clientY ??= viewportBounds.top + viewportBounds.height / 2;
      const paper = viewport.querySelector<HTMLElement>(
        "[data-document-canvas-paper]",
      )!;
      const paperBounds = paper.getBoundingClientRect();
      const paperXRatio = (clientX - paperBounds.left) / paperBounds.width;
      const paperYRatio = (clientY - paperBounds.top) / paperBounds.height;

      viewport.style.setProperty("--canvas-scale", String(scale));
      const nextPaperBounds = paper.getBoundingClientRect();
      viewport.scrollBy(
        nextPaperBounds.left + nextPaperBounds.width * paperXRatio - clientX,
        nextPaperBounds.top + nextPaperBounds.height * paperYRatio - clientY,
      );
      saveDocumentCanvasScale(scale);
      zoomRef.current = [scale, fitToWidth];
      setZoom(zoomRef.current);
    },
    [],
  );

  useLayoutEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) {
      return;
    }

    const handleWheel = (event: WheelEvent) => {
      if (!event.ctrlKey && !event.metaKey) {
        return;
      }

      event.preventDefault();
      setScale(
        zoomRef.current[0] * 2 ** (-event.deltaY / 300),
        event.clientX,
        event.clientY,
      );
    };

    viewport.addEventListener("wheel", handleWheel, { passive: false });
    viewport.style.setProperty(
      "--canvas-scale",
      String(zoomRef.current[0]),
    );
    const resizeObserver = new ResizeObserver(() => {
      const [, currentlyFitsWidth] = zoomRef.current;
      if (currentlyFitsWidth) {
        setScale(null);
      }
    });
    resizeObserver.observe(viewport);

    return () => {
      viewport.removeEventListener("wheel", handleWheel);
      resizeObserver.disconnect();
    };
  }, [setScale]);

  const onKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if ((!event.metaKey && !event.ctrlKey) || event.altKey) {
      return;
    }

    const scale =
      event.key === "0"
        ? 1
        : event.key === "+" || event.key === "="
          ? zoomRef.current[0] + 0.1
          : event.key === "-"
            ? zoomRef.current[0] - 0.1
            : null;
    if (scale === null) {
      return;
    }

    event.preventDefault();
    setScale(scale);
  };

  const onPointer = (event: PointerEvent<HTMLDivElement>) => {
    const viewport = event.currentTarget;
    const session = panSessionRef.current;

    if (event.type === "pointerdown") {
      if (event.pointerType !== "mouse") {
        return;
      }

      if (event.button === 0 || event.button === 1) {
        viewport.focus({ preventScroll: true });
      }

      const isOnPaper = Boolean(
        (event.target as Element).closest("[data-document-canvas-paper]"),
      );
      if (event.button !== 1 && (event.button !== 0 || isOnPaper)) {
        return;
      }

      event.preventDefault();
      viewport.setPointerCapture(event.pointerId);
      viewport.dataset.panning = "true";
      panSessionRef.current = [
        event.pointerId,
        viewport.scrollLeft,
        viewport.scrollTop,
        event.clientX,
        event.clientY,
      ];
      return;
    }

    if (!session) {
      return;
    }

    const [pointerId, scrollLeft, scrollTop, pointerX, pointerY] = session;
    if (pointerId !== event.pointerId) {
      return;
    }

    if (event.type === "pointermove") {
      viewport.scrollLeft = scrollLeft - (event.clientX - pointerX);
      viewport.scrollTop = scrollTop - (event.clientY - pointerY);
      return;
    }

    panSessionRef.current = null;
    viewport.dataset.panning = "false";
  };

  const [scale, isFitToWidth] = zoom;

  return {
    currentPage,
    isFitToWidth,
    onKeyDown,
    onPointer,
    onScroll,
    scale,
    setScale,
    viewportRef,
  };
}
