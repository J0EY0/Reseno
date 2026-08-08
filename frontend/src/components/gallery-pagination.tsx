import type { AppMessages } from "@/i18n";
import { useMemo } from "react";

import {
  Pagination,
  PaginationContent,
  PaginationEllipsis,
  PaginationItem,
  PaginationLink,
  PaginationNext,
  PaginationPrevious,
} from "@/components/ui/pagination";
import { cn } from "@/lib/utils";
import { runViewTransition } from "@/lib/view-transition";

type GalleryPaginationItem = number | "ellipsis";

function getPaginationItems(
  currentPage: number,
  totalPages: number,
): GalleryPaginationItem[] {
  if (totalPages <= 5) {
    return Array.from({ length: totalPages }, (_, index) => index + 1);
  }

  const pages = new Set([1, totalPages, currentPage]);

  if (currentPage > 2) {
    pages.add(currentPage - 1);
  }

  if (currentPage < totalPages - 1) {
    pages.add(currentPage + 1);
  }

  const sortedPages = [...pages].sort((a, b) => a - b);
  const items: GalleryPaginationItem[] = [];

  sortedPages.forEach((page, index) => {
    const previousPage = sortedPages[index - 1];

    if (previousPage && page - previousPage > 1) {
      items.push("ellipsis");
    }

    items.push(page);
  });

  return items;
}

export function GalleryPagination({
  currentPage,
  totalPages,
  t,
  onPageChange,
  disabled = false,
}: {
  currentPage: number;
  totalPages: number;
  t: AppMessages;
  onPageChange: (page: number) => void;
  disabled?: boolean;
}) {
  const pageItems = useMemo(
    () => getPaginationItems(currentPage, totalPages),
    [currentPage, totalPages],
  );

  if (totalPages <= 1) {
    return null;
  }

  function goToPage(page: number) {
    if (
      disabled ||
      page < 1 ||
      page > totalPages ||
      page === currentPage
    ) {
      return;
    }

    runViewTransition(
      () => onPageChange(page),
      page > currentPage ? "nav-forward" : "nav-back",
    );
  }

  return (
    <Pagination className="pt-4">
      <PaginationContent>
        <PaginationItem>
          <PaginationPrevious
            href="#"
            text={t.paginationPrevious}
            aria-label={t.paginationPrevious}
            aria-disabled={disabled || currentPage === 1}
            className={cn(
              (disabled || currentPage === 1) &&
                "pointer-events-none opacity-45",
            )}
            onClick={(event) => {
              event.preventDefault();
              goToPage(currentPage - 1);
            }}
          />
        </PaginationItem>

        {pageItems.map((item, index) =>
          item === "ellipsis" ? (
            <PaginationItem key={`ellipsis-${index}`}>
              <PaginationEllipsis />
            </PaginationItem>
          ) : (
            <PaginationItem key={item}>
              <PaginationLink
                href="#"
                isActive={item === currentPage}
                size="icon-sm"
                aria-disabled={disabled}
                className={cn(disabled && "pointer-events-none opacity-45")}
                onClick={(event) => {
                  event.preventDefault();
                  goToPage(item);
                }}
              >
                {item}
              </PaginationLink>
            </PaginationItem>
          ),
        )}

        <PaginationItem>
          <PaginationNext
            href="#"
            text={t.paginationNext}
            aria-label={t.paginationNext}
            aria-disabled={disabled || currentPage === totalPages}
            className={cn(
              (disabled || currentPage === totalPages) &&
                "pointer-events-none opacity-45",
            )}
            onClick={(event) => {
              event.preventDefault();
              goToPage(currentPage + 1);
            }}
          />
        </PaginationItem>
      </PaginationContent>
    </Pagination>
  );
}
