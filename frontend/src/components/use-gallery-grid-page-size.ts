import { useLayoutEffect, useRef, useState } from "react";

const fallbackGalleryColumns = 4;
const galleryItemSelector = ":scope > [data-gallery-item-id]";
const reflowDurationMs = 240;
const reflowEasing = "cubic-bezier(0.2, 0, 0, 1)";

type ItemPositions = Map<string, DOMRect>;

type ReflowTiming = {
  duration: number;
  easing: string;
  source: Animation;
};

function getReflowTiming(source: Animation): ReflowTiming {
  const timing = source.effect?.getTiming();
  const duration = Number(timing?.duration);

  return {
    duration: Number.isFinite(duration) ? duration : reflowDurationMs,
    easing: timing?.easing || reflowEasing,
    source,
  };
}

function getColumnCount(templateColumns: string) {
  if (!templateColumns || templateColumns === "none") {
    return fallbackGalleryColumns;
  }

  return Math.max(1, templateColumns.split(" ").filter(Boolean).length);
}

function getGridColumnCount(element: HTMLElement) {
  return getColumnCount(window.getComputedStyle(element).gridTemplateColumns);
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

function getSidebarWidthTransition(grid: HTMLElement) {
  return grid
    .closest('[data-slot="sidebar-wrapper"]')
    ?.querySelector<HTMLElement>('[data-slot="sidebar-gap"]')
    ?.getAnimations()
    .filter(
      (animation): animation is CSSTransition =>
        animation instanceof CSSTransition &&
        animation.transitionProperty === "width",
    )
    .at(-1);
}

function getReflowDuration(grid: HTMLElement) {
  const widthTransition = getSidebarWidthTransition(grid);

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

function getTransitionEndWidth(transition: CSSTransition) {
  const effect = transition.effect;

  if (!(effect instanceof KeyframeEffect)) {
    return null;
  }

  const keyframes = effect.getKeyframes();
  const width = Number.parseFloat(String(keyframes.at(-1)?.width ?? ""));

  return Number.isFinite(width) ? width : null;
}

function getGridTemplateAtWidth(grid: HTMLElement, width: number) {
  const measurement = grid.cloneNode(false) as HTMLElement;
  measurement.style.gridTemplateColumns = "";
  measurement.style.position = "fixed";
  measurement.style.left = "-10000px";
  measurement.style.top = "0";
  measurement.style.visibility = "hidden";
  measurement.style.width = `${width}px`;
  document.body.append(measurement);
  const templateColumns =
    window.getComputedStyle(measurement).gridTemplateColumns;
  measurement.remove();
  return templateColumns;
}

function isSingleRow(positions: ItemPositions) {
  const tops = new Set(
    Array.from(positions.values(), (position) => Math.round(position.top)),
  );
  return tops.size === 1;
}

function animateReflow(
  grid: HTMLElement,
  firstPositions: ItemPositions,
  activeAnimations: Map<HTMLElement, Animation>,
  timing?: ReflowTiming,
) {
  cancelAnimations(activeAnimations);
  const lastPositions = getItemPositions(grid);
  const duration = timing?.duration ?? getReflowDuration(grid);
  const easing = timing?.easing ?? reflowEasing;

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
      { duration, easing },
    );
    if (timing?.source.startTime != null) {
      animation.startTime = timing.source.startTime;
    } else if (timing) {
      void timing.source.ready.then(
        () => {
          if (
            activeAnimations.get(item) === animation &&
            timing.source.startTime != null
          ) {
            animation.startTime = timing.source.startTime;
          }
        },
        () => undefined,
      );
    } else {
      animation.startTime = document.timeline.currentTime;
    }
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
  const activeAnimationsRef = useRef(new Map<HTMLElement, Animation>());

  useLayoutEffect(() => {
    const grid = gridRef.current;

    if (!grid) {
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

    const sidebarWrapper = element.closest('[data-slot="sidebar-wrapper"]');
    let hasMeasuredInitialLayout = false;
    let originalGridTemplateColumns: string | null = null;
    let lockedTransition: CSSTransition | null = null;
    let disposed = false;
    let pendingFrame: number | null = null;

    const releaseGridTemplate = (animate = false) => {
      if (originalGridTemplateColumns === null) {
        return;
      }

      const firstPositions = animate ? getItemPositions(element) : null;
      const timingSource = animate
        ? getSidebarWidthTransition(element)
        : undefined;
      element.style.gridTemplateColumns = originalGridTemplateColumns;
      originalGridTemplateColumns = null;
      lockedTransition = null;
      if (firstPositions) {
        animateReflow(
          element,
          firstPositions,
          activeAnimations,
          timingSource ? getReflowTiming(timingSource) : undefined,
        );
      }
      const nextColumnCount = getGridColumnCount(element);
      columnCountRef.current = nextColumnCount;
      itemPositionsRef.current = getItemPositions(element);
      setColumnCount(nextColumnCount);
    };

    const prepareExpandedGrid = () => {
      const sidebar = sidebarWrapper?.querySelector<HTMLElement>(
        '[data-slot="sidebar"][data-state]',
      );
      const sidebarGap = sidebarWrapper?.querySelector<HTMLElement>(
        '[data-slot="sidebar-gap"]',
      );

      if (!sidebarGap || sidebar?.dataset.state !== "expanded") {
        return false;
      }

      const widthTransition = getSidebarWidthTransition(element);
      const targetSidebarWidth = widthTransition
        ? getTransitionEndWidth(widthTransition)
        : null;

      if (!widthTransition || targetSidebarWidth === null) {
        return false;
      }

      const firstPositions = getItemPositions(element);

      if (!isSingleRow(firstPositions) || firstPositions.size === 0) {
        return true;
      }

      const gridWidth = element.getBoundingClientRect().width;
      const sidebarWidth = sidebarGap.getBoundingClientRect().width;
      const targetGridWidth = gridWidth + sidebarWidth - targetSidebarWidth;
      const targetTemplateColumns = getGridTemplateAtWidth(
        element,
        targetGridWidth,
      );
      const targetColumnCount = getColumnCount(targetTemplateColumns);

      if (
        targetColumnCount < firstPositions.size ||
        targetColumnCount === columnCountRef.current
      ) {
        return true;
      }

      originalGridTemplateColumns ??= element.style.gridTemplateColumns;
      element.style.gridTemplateColumns = targetTemplateColumns;
      animateReflow(
        element,
        firstPositions,
        activeAnimations,
        getReflowTiming(widthTransition),
      );
      lockedTransition = widthTransition;
      columnCountRef.current = targetColumnCount;
      itemPositionsRef.current = getItemPositions(element);

      void widthTransition.finished.then(
        () => {
          if (!disposed && lockedTransition === widthTransition) {
            releaseGridTemplate();
          }
        },
        () => {
          requestAnimationFrame(() => {
            if (
              !disposed &&
              lockedTransition === widthTransition &&
              !getSidebarWidthTransition(element)
            ) {
              releaseGridTemplate();
              cancelAnimations(activeAnimations);
            }
          });
        },
      );
      return true;
    };

    const handleSidebarStateChange = () => {
      const sidebar = sidebarWrapper?.querySelector<HTMLElement>(
        '[data-slot="sidebar"][data-state]',
      );

      if (sidebar?.dataset.state !== "expanded") {
        if (pendingFrame !== null) {
          cancelAnimationFrame(pendingFrame);
          pendingFrame = null;
        }
        releaseGridTemplate(true);
        return;
      }

      if (prepareExpandedGrid() || pendingFrame !== null) {
        return;
      }

      pendingFrame = requestAnimationFrame(() => {
        pendingFrame = null;
        prepareExpandedGrid();
      });
    };

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
        animateReflow(element, itemPositionsRef.current, activeAnimations);
        columnCountRef.current = nextColumnCount;
        itemPositionsRef.current = getItemPositions(element);
        setColumnCount(nextColumnCount);
      } else {
        itemPositionsRef.current = getItemPositions(element);
      }
    };

    syncColumnCount();

    const resizeObserver = new ResizeObserver(syncColumnCount);
    const sidebarObserver = sidebarWrapper
      ? new MutationObserver(handleSidebarStateChange)
      : null;

    resizeObserver.observe(element);
    if (sidebarWrapper) {
      sidebarObserver?.observe(sidebarWrapper, {
        attributeFilter: ["data-state"],
        subtree: true,
      });
    }

    return () => {
      disposed = true;
      resizeObserver.disconnect();
      sidebarObserver?.disconnect();
      if (pendingFrame !== null) {
        cancelAnimationFrame(pendingFrame);
      }
      if (originalGridTemplateColumns !== null) {
        element.style.gridTemplateColumns = originalGridTemplateColumns;
      }
      cancelAnimations(activeAnimations);
    };
  }, []);

  return {
    gridRef,
    pageSize: Math.max(1, columnCount * rows - fixedItems),
  };
}
