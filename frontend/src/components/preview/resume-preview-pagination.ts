import { useLayoutEffect, useRef, useState } from "react";

import {
  A4_HEIGHT_MM,
  A4_WIDTH_MM,
  type ResumePreviewModel,
} from "@/components/preview/resume-preview-model";

interface ResumePageSlice {
  startOffsetMm: number;
  visibleHeightMm: number;
}

export interface ResumePaginationState {
  pages: ResumePageSlice[];
}

interface VerticalInterval {
  bottom: number;
  top: number;
}

const PAGE_BREAK_EPSILON_PX = 0.5;
const PAGINATION_STABLE_FRAME_COUNT = 2;
const MM_PRECISION = 1000;

function getPaginationSignature(pagination: ResumePaginationState) {
  return pagination.pages
    .map(
      ({ startOffsetMm, visibleHeightMm }) =>
        `${startOffsetMm.toFixed(3)}:${visibleHeightMm.toFixed(3)}`,
    )
    .join("|");
}

function roundMm(value: number) {
  return Math.round(value * MM_PRECISION) / MM_PRECISION;
}

function getInterval(
  element: Element,
  rootRect: DOMRect,
): VerticalInterval | null {
  const rect = element.getBoundingClientRect();
  const top = rect.top - rootRect.top;
  const bottom = rect.bottom - rootRect.top;

  if (
    !Number.isFinite(top) ||
    !Number.isFinite(bottom) ||
    bottom - top <= PAGE_BREAK_EPSILON_PX
  ) {
    return null;
  }

  return { top, bottom };
}

function collectBlockIntervals(element: HTMLElement, rootRect: DOMRect) {
  const contentElement = element.querySelector<HTMLElement>(
    '[data-resume-flow-content="true"]',
  );
  if (!contentElement) {
    return [];
  }

  const intervals: VerticalInterval[] = [];
  contentElement
    .querySelectorAll<HTMLElement>(
      'p, li, [data-resume-page-block="true"]',
    )
    .forEach((block) => {
      const interval = getInterval(block, rootRect);
      if (interval) {
        intervals.push(interval);
      }
    });

  contentElement
    .querySelectorAll<HTMLElement>("[data-resume-section-id]")
    .forEach((section) => {
      const header = section.querySelector<HTMLElement>(
        '[data-resume-section-header="true"]',
      );
      const firstContentBlock = section.querySelector<HTMLElement>(
        'p, li, [data-resume-page-block="true"]',
      );
      if (!header || !firstContentBlock) {
        return;
      }

      const sectionInterval = getInterval(section, rootRect);
      const firstContentInterval = getInterval(firstContentBlock, rootRect);
      if (!sectionInterval || !firstContentInterval) {
        return;
      }

      intervals.push({
        top: sectionInterval.top,
        bottom: firstContentInterval.bottom,
      });
    });

  return intervals;
}

function collectTextLineIntervals(element: HTMLElement, rootRect: DOMRect) {
  const contentElement = element.querySelector<HTMLElement>(
    '[data-resume-flow-content="true"]',
  );
  if (!contentElement) {
    return [];
  }

  const intervals: VerticalInterval[] = [];
  const walker = document.createTreeWalker(
    contentElement,
    NodeFilter.SHOW_TEXT,
    {
      acceptNode(node) {
        return node.textContent?.trim()
          ? NodeFilter.FILTER_ACCEPT
          : NodeFilter.FILTER_REJECT;
      },
    },
  );
  const range = document.createRange();
  let textNode = walker.nextNode();

  while (textNode) {
    range.selectNodeContents(textNode);
    for (const rect of range.getClientRects()) {
      const top = rect.top - rootRect.top;
      const bottom = rect.bottom - rootRect.top;
      if (bottom - top > PAGE_BREAK_EPSILON_PX) {
        intervals.push({ top, bottom });
      }
    }
    textNode = walker.nextNode();
  }

  return intervals;
}

function findSafePageEnd({
  blockIntervals,
  lineIntervals,
  nominalEnd,
  pageHeight,
  pageStart,
}: {
  blockIntervals: VerticalInterval[];
  lineIntervals: VerticalInterval[];
  nominalEnd: number;
  pageHeight: number;
  pageStart: number;
}) {
  // Keep short semantic blocks together. Line boxes remain the fallback for
  // blocks taller than a page, so long content can still make progress.
  const protectedIntervals = [
    ...blockIntervals.filter(
      ({ bottom, top }) =>
        bottom - top < pageHeight - PAGE_BREAK_EPSILON_PX &&
        top > pageStart + PAGE_BREAK_EPSILON_PX,
    ),
    ...lineIntervals.filter(
      ({ top }) => top > pageStart + PAGE_BREAK_EPSILON_PX,
    ),
  ];
  let pageEnd = nominalEnd;

  // Retreat until the boundary no longer lands inside any protected interval.
  // A single retreat can expose an earlier overlapping line or block.
  for (let index = 0; index <= protectedIntervals.length; index += 1) {
    let nextPageEnd = pageEnd;

    for (const interval of protectedIntervals) {
      const crossesPageEnd =
        interval.top < pageEnd - PAGE_BREAK_EPSILON_PX &&
        interval.bottom > pageEnd + PAGE_BREAK_EPSILON_PX;
      if (crossesPageEnd) {
        nextPageEnd = Math.min(nextPageEnd, interval.top);
      }
    }

    if (nextPageEnd >= pageEnd - PAGE_BREAK_EPSILON_PX) {
      break;
    }
    pageEnd = nextPageEnd;
  }

  return pageEnd > pageStart + PAGE_BREAK_EPSILON_PX
    ? pageEnd
    : nominalEnd;
}

function createPageSlices({
  blockIntervals,
  contentHeight,
  lineIntervals,
  pageHeight,
  pageHeightMm,
  pxPerMm,
}: {
  blockIntervals: VerticalInterval[];
  contentHeight: number;
  lineIntervals: VerticalInterval[];
  pageHeight: number;
  pageHeightMm: number;
  pxPerMm: number;
}) {
  const pages: ResumePageSlice[] = [];
  let pageStart = 0;

  while (pageStart + pageHeight < contentHeight - PAGE_BREAK_EPSILON_PX) {
    const nominalEnd = pageStart + pageHeight;
    const pageEnd = findSafePageEnd({
      blockIntervals,
      lineIntervals,
      nominalEnd,
      pageHeight,
      pageStart,
    });

    pages.push({
      startOffsetMm: roundMm(pageStart / pxPerMm),
      visibleHeightMm: roundMm((pageEnd - pageStart) / pxPerMm),
    });
    pageStart = pageEnd;
  }

  pages.push({
    startOffsetMm: roundMm(pageStart / pxPerMm),
    visibleHeightMm: pageHeightMm,
  });

  return pages;
}

function calculateResumePagination({
  contentWidthMm,
  element,
  pageHeightMm,
}: {
  contentWidthMm: number;
  element: HTMLElement;
  pageHeightMm: number;
}) {
  const rootRect = element.getBoundingClientRect();
  const pxPerMm = rootRect.width / contentWidthMm;
  if (!Number.isFinite(pxPerMm) || pxPerMm <= 0) {
    return {
      pages: [{ startOffsetMm: 0, visibleHeightMm: pageHeightMm }],
    };
  }

  const pageHeight = pageHeightMm * pxPerMm;
  const contentElement = element.querySelector<HTMLElement>(
    '[data-resume-flow-content="true"]',
  );
  const contentRect = contentElement?.getBoundingClientRect() ?? rootRect;
  const contentHeight = Math.max(0, contentRect.bottom - rootRect.top);

  return {
    pages: createPageSlices({
      blockIntervals: collectBlockIntervals(element, rootRect),
      contentHeight,
      lineIntervals: collectTextLineIntervals(element, rootRect),
      pageHeight,
      pageHeightMm,
      pxPerMm,
    }),
  };
}

export function useResumePagination(
  model: ResumePreviewModel,
  resumeFontReadyToken: object | null,
) {
  const measureRef = useRef<HTMLDivElement | null>(null);
  const pageHeightMm = model.isSidebarLayout
    ? A4_HEIGHT_MM
    : model.standardContentHeightMm;
  const [pagination, setPagination] = useState<ResumePaginationState>({
    pages: [{ startOffsetMm: 0, visibleHeightMm: pageHeightMm }],
  });
  const [paginationReadyToken, setPaginationReadyToken] =
    useState<object | null>(null);
  const isPaginationReady = Boolean(
    resumeFontReadyToken && paginationReadyToken === resumeFontReadyToken,
  );

  useLayoutEffect(() => {
    const element = measureRef.current;

    if (!element) {
      return;
    }

    const measurePages = () => {
      const nextPagination = calculateResumePagination({
        element,
        contentWidthMm: model.isSidebarLayout
          ? A4_WIDTH_MM
          : model.standardContentWidthMm,
        pageHeightMm,
      });
      const nextSignature = getPaginationSignature(nextPagination);

      setPagination((currentPagination) =>
        getPaginationSignature(currentPagination) === nextSignature
          ? currentPagination
          : nextPagination,
      );

      return nextSignature;
    };

    // The visible content and its page slices must update in the same paint.
    // Font stability still gates export readiness, but not this correctness pass.
    measurePages();

    if (!resumeFontReadyToken) {
      return;
    }

    let animationFrameId = 0;
    let lastPaginationSignature: string | null = null;
    let matchingFrameCount = 0;

    const syncPages = () => {
      animationFrameId = 0;
      const nextSignature = measurePages();

      if (lastPaginationSignature === nextSignature) {
        matchingFrameCount += 1;
      } else {
        lastPaginationSignature = nextSignature;
        matchingFrameCount = 1;
      }

      if (matchingFrameCount >= PAGINATION_STABLE_FRAME_COUNT) {
        setPaginationReadyToken(resumeFontReadyToken);
        return;
      }

      animationFrameId = window.requestAnimationFrame(syncPages);
    };

    const scheduleSync = () => {
      if (animationFrameId) {
        window.cancelAnimationFrame(animationFrameId);
      }

      lastPaginationSignature = null;
      matchingFrameCount = 0;
      setPaginationReadyToken(null);
      animationFrameId = window.requestAnimationFrame(syncPages);
    };

    scheduleSync();

    if (typeof ResizeObserver === "undefined") {
      return () => {
        if (animationFrameId) {
          window.cancelAnimationFrame(animationFrameId);
        }
      };
    }

    let isInitialObservation = true;
    const resizeObserver = new ResizeObserver(() => {
      if (isInitialObservation) {
        isInitialObservation = false;
        return;
      }
      scheduleSync();
    });
    resizeObserver.observe(element);

    return () => {
      if (animationFrameId) {
        window.cancelAnimationFrame(animationFrameId);
      }

      resizeObserver.disconnect();
    };
  }, [model, pageHeightMm, resumeFontReadyToken]);

  return { isPaginationReady, measureRef, pagination };
}
