import { useLayoutEffect, useRef, useState } from "react";

const fallbackGalleryColumns = 4;

function getGridColumnCount(element: HTMLElement) {
  const templateColumns = window.getComputedStyle(element).gridTemplateColumns;

  if (!templateColumns || templateColumns === "none") {
    return fallbackGalleryColumns;
  }

  return Math.max(1, templateColumns.split(" ").filter(Boolean).length);
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

  useLayoutEffect(() => {
    const element = gridRef.current;

    if (!element) {
      return;
    }

    const syncColumnCount = () => {
      const nextColumnCount = getGridColumnCount(element);

      setColumnCount((current) =>
        current === nextColumnCount ? current : nextColumnCount,
      );
    };

    syncColumnCount();

    const resizeObserver = new ResizeObserver(syncColumnCount);

    resizeObserver.observe(element);

    return () => resizeObserver.disconnect();
  }, []);

  return {
    gridRef,
    pageSize: Math.max(1, columnCount * rows - fixedItems),
  };
}
