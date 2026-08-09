import { useLayoutEffect, useRef, useState } from "react";

import {
  A4_HEIGHT_MM,
  A4_WIDTH_MM,
  getRenderableItems,
  type ResumePreviewModel,
} from "@/components/preview/resume-preview-model";
import type { RenderableResumeSection } from "@/lib/resume-sections";

export interface ResumePaginationState {
  breakBeforeSectionSpacers: Record<string, number>;
  pageCount: number;
}

const PAGINATION_TOLERANCE_PX = 8;
const PAGINATION_STABLE_FRAME_COUNT = 2;

function getPaginationSignature(pagination: ResumePaginationState) {
  const spacers = Object.entries(pagination.breakBeforeSectionSpacers)
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([sectionId, spacer]) => `${sectionId}:${Math.round(spacer)}`)
    .join(",");

  return `${pagination.pageCount}|${spacers}`;
}

function getOffsetTopWithin(element: HTMLElement, ancestor: HTMLElement) {
  let top = 0;
  let current: HTMLElement | null = element;

  while (current && current !== ancestor) {
    top += current.offsetTop;
    current = current.offsetParent as HTMLElement | null;
  }

  return top;
}

function parsePixelValue(value: string) {
  const parsed = Number.parseFloat(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function measureSectionBlocks(
  element: HTMLElement,
  sections: RenderableResumeSection[],
) {
  const measures = new Map<string, { headerBlockHeight: number }>();

  sections.forEach((section) => {
    const sectionElement = element.querySelector<HTMLElement>(
      `[data-resume-section-id="${section.id}"]`,
    );

    if (!sectionElement) {
      return;
    }

    const firstItemElement = sectionElement.querySelector<HTMLElement>(
      "[data-resume-item-id]",
    );
    const headerBlockHeight = firstItemElement
      ? getOffsetTopWithin(firstItemElement, sectionElement)
      : sectionElement.offsetHeight;

    measures.set(section.id, { headerBlockHeight });
  });

  return measures;
}

function calculateResumePagination({
  contentWidthMm,
  element,
  pageHeightMm,
  sections,
}: {
  contentWidthMm: number;
  element: HTMLElement;
  pageHeightMm: number;
  sections: RenderableResumeSection[];
}) {
  const layoutWidth = element.offsetWidth || element.clientWidth;
  const pxPerMm = layoutWidth > 0 ? layoutWidth / contentWidthMm : 1;
  const pageHeight =
    layoutWidth > 0
      ? Math.round(pageHeightMm * pxPerMm)
      : element.scrollHeight || 1;
  const contentElement = element.querySelector<HTMLElement>(
    '[data-resume-flow-content="true"]',
  );
  const sectionMeasures = measureSectionBlocks(element, sections);
  const breakBeforeSectionSpacers: Record<string, number> = {};

  sections.forEach((section) => {
    const items = getRenderableItems(section);
    const measure = sectionMeasures.get(section.id);
    const sectionElement = element.querySelector<HTMLElement>(
      `[data-resume-section-id="${section.id}"]`,
    );

    if (items.length === 0 || !measure || !sectionElement) {
      return;
    }

    const sectionStyle = window.getComputedStyle(sectionElement);
    const currentSpacer = parsePixelValue(sectionStyle.marginTop);
    const sectionTop =
      getOffsetTopWithin(sectionElement, element) - currentSpacer;
    const offsetWithinPage = sectionTop % pageHeight;
    const remainingOnPage = pageHeight - offsetWithinPage;
    const followingContentVisibleOnPage =
      remainingOnPage - measure.headerBlockHeight;

    if (
      offsetWithinPage > PAGINATION_TOLERANCE_PX &&
      followingContentVisibleOnPage <= PAGINATION_TOLERANCE_PX
    ) {
      breakBeforeSectionSpacers[section.id] = remainingOnPage;
    }
  });

  const measuredContentHeight = contentElement
    ? contentElement.offsetTop + contentElement.offsetHeight
    : element.scrollHeight;
  const addedSpacerDelta = Object.entries(breakBeforeSectionSpacers).reduce(
    (total, [sectionId, spacer]) => {
      const sectionElement = element.querySelector<HTMLElement>(
        `[data-resume-section-id="${sectionId}"]`,
      );
      const currentSpacer = sectionElement
        ? parsePixelValue(window.getComputedStyle(sectionElement).marginTop)
        : 0;

      return total + Math.max(0, spacer - currentSpacer);
    },
    0,
  );
  const pageCount = Math.max(
    1,
    Math.ceil(
      Math.max(measuredContentHeight + addedSpacerDelta, 0) / pageHeight,
    ),
  );

  return { pageCount, breakBeforeSectionSpacers };
}

export function useResumePagination(
  model: ResumePreviewModel,
  resumeFontReadyToken: object | null,
) {
  const measureRef = useRef<HTMLDivElement | null>(null);
  const [pagination, setPagination] = useState<ResumePaginationState>({
    pageCount: 1,
    breakBeforeSectionSpacers: {},
  });
  const [paginationReadyToken, setPaginationReadyToken] =
    useState<object | null>(null);
  const isPaginationReady = Boolean(
    resumeFontReadyToken && paginationReadyToken === resumeFontReadyToken,
  );

  useLayoutEffect(() => {
    if (!resumeFontReadyToken) {
      return;
    }

    const element = measureRef.current;

    if (!element) {
      return;
    }

    let animationFrameId = 0;
    let lastPaginationSignature: string | null = null;
    let matchingFrameCount = 0;

    const syncPages = () => {
      animationFrameId = 0;

      const nextPagination = calculateResumePagination({
        element,
        sections: model.visibleSections,
        contentWidthMm: model.isSidebarLayout
          ? A4_WIDTH_MM
          : model.standardContentWidthMm,
        pageHeightMm: model.isSidebarLayout
          ? A4_HEIGHT_MM
          : model.standardContentHeightMm,
      });
      const nextSignature = getPaginationSignature(nextPagination);

      setPagination((currentPagination) =>
        getPaginationSignature(currentPagination) === nextSignature
          ? currentPagination
          : nextPagination,
      );

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

    const resizeObserver = new ResizeObserver(scheduleSync);
    resizeObserver.observe(element);

    return () => {
      if (animationFrameId) {
        window.cancelAnimationFrame(animationFrameId);
      }

      resizeObserver.disconnect();
    };
  }, [model, resumeFontReadyToken]);

  return { isPaginationReady, measureRef, pagination };
}
