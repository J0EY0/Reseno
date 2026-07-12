import type { AppMessages } from "@/i18n";
import { ChevronLeftIcon, ChevronRightIcon } from "lucide-react";
import { useMemo } from "react";

import {
  Pagination,
  PaginationContent,
  PaginationEllipsis,
  PaginationItem,
  PaginationLink,
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
}: {
  currentPage: number;
  totalPages: number;
  t: AppMessages;
  onPageChange: (page: number) => void;
}) {
  const pageItems = useMemo(
    () => getPaginationItems(currentPage, totalPages),
    [currentPage, totalPages],
  );

  if (totalPages <= 1) {
    return null;
  }

  function goToPage(page: number) {
    if (page < 1 || page > totalPages || page === currentPage) {
      return;
    }

    runViewTransition(
      () => onPageChange(page),
      page > currentPage ? "nav-forward" : "nav-back",
    );
  }

  return (
    <Pagination className="pt-4">
      <PaginationContent className="rounded-full border border-border/70 bg-background/80 px-2 py-1 shadow-sm backdrop-blur">
        <PaginationItem>
          <PaginationLink
            href="#"
            aria-label={t.paginationPrevious}
            aria-disabled={currentPage === 1}
            className={cn(
              "h-8 gap-1 rounded-full px-2.5 text-xs",
              currentPage === 1 && "pointer-events-none opacity-45",
            )}
            onClick={(event) => {
              event.preventDefault();
              goToPage(currentPage - 1);
            }}
          >
            <ChevronLeftIcon />
            <span className="hidden sm:block">{t.paginationPrevious}</span>
          </PaginationLink>
        </PaginationItem>

        {pageItems.map((item, index) =>
          item === "ellipsis" ? (
            <PaginationItem key={`ellipsis-${index}`}>
              <PaginationEllipsis className="size-8" />
            </PaginationItem>
          ) : (
            <PaginationItem key={item}>
              <PaginationLink
                href="#"
                isActive={item === currentPage}
                className="size-8 rounded-full text-xs"
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
          <PaginationLink
            href="#"
            aria-label={t.paginationNext}
            aria-disabled={currentPage === totalPages}
            className={cn(
              "h-8 gap-1 rounded-full px-2.5 text-xs",
              currentPage === totalPages && "pointer-events-none opacity-45",
            )}
            onClick={(event) => {
              event.preventDefault();
              goToPage(currentPage + 1);
            }}
          >
            <span className="hidden sm:block">{t.paginationNext}</span>
            <ChevronRightIcon />
          </PaginationLink>
        </PaginationItem>
      </PaginationContent>
    </Pagination>
  );
}
