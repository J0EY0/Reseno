import { useLayoutEffect, useRef, useState } from "react";

const fallbackGalleryColumns = 4;
const galleryItemSelector = ":scope > [data-gallery-item-id]";
const reflowDurationMs = 240;
const reflowEasing = "cubic-bezier(0.2, 0, 0, 1)";

type ItemPositions = Map<string, DOMRect>;

type PendingReflow = {
  targetColumnCount: number;
  firstPositions: ItemPositions;
};

function getGridColumnCount(element: HTMLElement) {
  const templateColumns = window.getComputedStyle(element).gridTemplateColumns;

  if (!templateColumns || templateColumns === "none") {
    return fallbackGalleryColumns;
  }

  return Math.max(1, templateColumns.split(" ").filter(Boolean).length);
}

function getItemPositions(element: HTMLElement): ItemPositions {
  const positions: ItemPositions = new Map();

  for (const item of Array.from(
    element.querySelectorAll<HTMLElement>(galleryItemSelector),
  )) {
    const id = item.dataset.galleryItemId;

    if (id) {
      positions.set(id, item.getBoundingClientRect());
    }
  }

  return positions;
}

function cancelAnimations(animations: Map<HTMLElement, Animation>) {
  for (const animation of animations.values()) {
    animation.cancel();
  }
  animations.clear();
}

function getReflowDuration(grid: HTMLElement) {
  const sidebarGap = grid
    .closest('[data-slot="sidebar-wrapper"]')
    ?.querySelector<HTMLElement>('[data-slot="sidebar-gap"]');
  const widthTransition = sidebarGap
    ?.getAnimations()
    .find(
      (animation): animation is CSSTransition =>
        animation instanceof CSSTransition &&
        animation.transitionProperty === "width",
    );

  if (!widthTransition) {
    return reflowDurationMs;
  }

  const timing = widthTransition.effect?.getComputedTiming();
  return Math.max(
    0,
    Number(timing?.endTime ?? reflowDurationMs) -
      Number(widthTransition.currentTime ?? 0),
  );
}

function animateReflow(
  grid: HTMLElement,
  firstPositions: ItemPositions,
  activeAnimations: Map<HTMLElement, Animation>,
) {
  cancelAnimations(activeAnimations);
  const lastPositions = getItemPositions(grid);
  const duration = getReflowDuration(grid);

  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    return;
  }

  for (const item of Array.from(
    grid.querySelectorAll<HTMLElement>(galleryItemSelector),
  )) {
    const id = item.dataset.galleryItemId;
    const first = id ? firstPositions.get(id) : undefined;
    const last = id ? lastPositions.get(id) : undefined;

    if (!first || !last) {
      continue;
    }

    const offsetX = first.left - last.left;
    const offsetY = first.top - last.top;

    if (Math.abs(offsetX) < 0.5 && Math.abs(offsetY) < 0.5) {
      continue;
    }

    const animation = item.animate(
      [
        { transform: `translate3d(${offsetX}px, ${offsetY}px, 0)` },
        { transform: "translate3d(0, 0, 0)" },
      ],
      { duration, easing: reflowEasing },
    );
    animation.startTime = document.timeline.currentTime;
    animation.id = "gallery-grid-reflow";
    activeAnimations.set(item, animation);

    const removeAnimation = () => {
      if (activeAnimations.get(item) === animation) {
        activeAnimations.delete(item);
      }
    };
    animation.addEventListener("finish", removeAnimation, { once: true });
    animation.addEventListener("cancel", removeAnimation, { once: true });
  }
}

export function useGalleryGridPageSize({
  fixedItems = 1,
  rows = 2,
}: {
  fixedItems?: number;
  rows?: number;
}) {
  const gridRef = useRef<HTMLDivElement | null>(null);
  const [columnCount, setColumnCount] = useState(fallbackGalleryColumns);
  const columnCountRef = useRef(fallbackGalleryColumns);
  const itemPositionsRef = useRef<ItemPositions>(new Map());
  const pendingReflowRef = useRef<PendingReflow | null>(null);
  const activeAnimationsRef = useRef(new Map<HTMLElement, Animation>());

  useLayoutEffect(() => {
    const grid = gridRef.current;
    const pendingReflow = pendingReflowRef.current;

    if (!grid) {
      return;
    }

    if (
      pendingReflow &&
      pendingReflow.targetColumnCount === columnCount
    ) {
      animateReflow(
        grid,
        pendingReflow.firstPositions,
        activeAnimationsRef.current,
      );
      pendingReflowRef.current = null;
      itemPositionsRef.current = pendingReflow.firstPositions;
      return;
    }

    itemPositionsRef.current = getItemPositions(grid);
  });

  useLayoutEffect(() => {
    const element = gridRef.current;
    const activeAnimations = activeAnimationsRef.current;

    if (!element) {
      return;
    }

    let hasMeasuredInitialLayout = false;

    const syncColumnCount = () => {
      const nextColumnCount = getGridColumnCount(element);

      if (!hasMeasuredInitialLayout) {
        hasMeasuredInitialLayout = true;
        columnCountRef.current = nextColumnCount;
        itemPositionsRef.current = getItemPositions(element);
        setColumnCount(nextColumnCount);
        return;
      }

      if (columnCountRef.current !== nextColumnCount) {
        pendingReflowRef.current = {
          targetColumnCount: nextColumnCount,
          firstPositions: itemPositionsRef.current,
        };
        columnCountRef.current = nextColumnCount;
        setColumnCount(nextColumnCount);
      } else if (!pendingReflowRef.current) {
        itemPositionsRef.current = getItemPositions(element);
      }
    };

    syncColumnCount();

    const resizeObserver = new ResizeObserver(syncColumnCount);

    resizeObserver.observe(element);

    return () => {
      resizeObserver.disconnect();
      pendingReflowRef.current = null;
      cancelAnimations(activeAnimations);
    };
  }, []);

  return {
    gridRef,
    pageSize: Math.max(1, columnCount * rows - fixedItems),
  };
}
