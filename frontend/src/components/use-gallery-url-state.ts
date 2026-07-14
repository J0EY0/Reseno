import { useCallback } from "react";
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
  const searchQuery = searchParams.get("q") ?? "";
  const currentPage = parsePage(searchParams.get("page"));

  const setSearchQuery = useCallback(
    (value: string) => {
      // Search keystrokes replace the current entry; explicit page changes below
      // still push history so Back/Forward restores the user's navigation.
      setSearchParams(
        (current) => {
          const next = new URLSearchParams(current);

          if (value) {
            next.set("q", value);
          } else {
            next.delete("q");
          }

          next.delete("page");
          return next;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  const setCurrentPage = useCallback(
    (page: number) => {
      setSearchParams((current) => {
        const next = new URLSearchParams(current);

        if (page > 1) {
          next.set("page", String(page));
        } else {
          next.delete("page");
        }

        return next;
      });
    },
    [setSearchParams],
  );

  return { currentPage, searchQuery, setCurrentPage, setSearchQuery };
}
