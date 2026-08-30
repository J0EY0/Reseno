import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";

function parsePage(value: string | null) {
  if (!value) {
    return 1;
  }

  const page = Number(value);
  return Number.isSafeInteger(page) && page > 0 ? page : 1;
}

export function useGalleryUrlState() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [localSearchParams, setLocalSearchParams] = useState(
    () => new URLSearchParams(searchParams),
  );
  const desiredSearchParamsRef = useRef(localSearchParams);
  const searchQuery = localSearchParams.get("q") ?? "";
  const currentPage = parsePage(localSearchParams.get("page"));

  useEffect(() => {
    function handlePopState() {
      const nextSearchParams = new URLSearchParams(window.location.search);
      desiredSearchParamsRef.current = nextSearchParams;
      setLocalSearchParams(nextSearchParams);
    }

    // This hook owns gallery PUSH/REPLACE updates while mounted. Native POP
    // navigation is the only external event that replaces the local intent.
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  const setSearchQuery = useCallback(
    (value: string) => {
      const next = new URLSearchParams(desiredSearchParamsRef.current);

      if (value) {
        next.set("q", value);
      } else {
        next.delete("q");
      }

      next.delete("page");
      const serializedNext = next.toString();
      setLocalSearchParams(next);
      if (serializedNext === desiredSearchParamsRef.current.toString()) {
        return;
      }

      desiredSearchParamsRef.current = next;
      // Search keystrokes replace the current entry; explicit page changes below
      // still push history so Back/Forward restores the user's navigation.
      setSearchParams(next, { replace: true });
    },
    [setSearchParams],
  );

  const setCurrentPage = useCallback(
    (page: number) => {
      const next = new URLSearchParams(desiredSearchParamsRef.current);

      if (page > 1) {
        next.set("page", String(page));
      } else {
        next.delete("page");
      }

      const serializedNext = next.toString();
      setLocalSearchParams(next);
      if (serializedNext === desiredSearchParamsRef.current.toString()) {
        return;
      }

      desiredSearchParamsRef.current = next;
      setSearchParams(next);
    },
    [setSearchParams],
  );

  return {
    currentPage,
    searchQuery,
    setCurrentPage,
    setSearchQuery,
  };
}
