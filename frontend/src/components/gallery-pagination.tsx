import type { AppMessages } from "@/i18n";
import { startTransition, useMemo, type MouseEvent } from "react";
import { useLocation } from "react-router-dom";

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

type GalleryPaginationItem = number | "ellipsis";

function isPlainPrimaryClick(event: MouseEvent<HTMLAnchorElement>) {
  return (
    event.button === 0 &&
    !event.metaKey &&
    !event.ctrlKey &&
    !event.shiftKey &&
    !event.altKey
  );
}

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
  const location = useLocation();
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

    startTransition(() => onPageChange(page));
  }

  function getPageHref(page: number) {
    const nextSearchParams = new URLSearchParams(location.search);

    if (page > 1) {
      nextSearchParams.set("page", String(page));
    } else {
      nextSearchParams.delete("page");
    }

    const search = nextSearchParams.toString();
    return `${location.pathname}${search ? `?${search}` : ""}${location.hash}`;
  }

  function handlePageClick(
    event: MouseEvent<HTMLAnchorElement>,
    page: number,
    unavailable: boolean,
  ) {
    if (unavailable) {
      event.preventDefault();
      return;
    }

    if (!isPlainPrimaryClick(event)) {
      return;
    }

    event.preventDefault();
    goToPage(page);
  }

  const previousUnavailable = disabled || currentPage === 1;
  const nextUnavailable = disabled || currentPage === totalPages;

  return (
    <Pagination className="pt-4">
      <PaginationContent>
        <PaginationItem>
          <PaginationPrevious
            href={
              previousUnavailable
                ? undefined
                : getPageHref(currentPage - 1)
            }
            text={t.paginationPrevious}
            aria-label={t.paginationPrevious}
            aria-disabled={previousUnavailable}
            tabIndex={previousUnavailable ? -1 : undefined}
            className={cn(
              previousUnavailable && "pointer-events-none opacity-45",
            )}
            onClick={(event) => {
              handlePageClick(
                event,
                currentPage - 1,
                previousUnavailable,
              );
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
                href={disabled ? undefined : getPageHref(item)}
                isActive={item === currentPage}
                size="icon-sm"
                aria-disabled={disabled}
                tabIndex={disabled ? -1 : undefined}
                className={cn(disabled && "pointer-events-none opacity-45")}
                onClick={(event) => {
                  handlePageClick(event, item, disabled);
                }}
              >
                {item}
              </PaginationLink>
            </PaginationItem>
          ),
        )}

        <PaginationItem>
          <PaginationNext
            href={
              nextUnavailable ? undefined : getPageHref(currentPage + 1)
            }
            text={t.paginationNext}
            aria-label={t.paginationNext}
            aria-disabled={nextUnavailable}
            tabIndex={nextUnavailable ? -1 : undefined}
            className={cn(
              nextUnavailable && "pointer-events-none opacity-45",
            )}
            onClick={(event) => {
              handlePageClick(event, currentPage + 1, nextUnavailable);
            }}
          />
        </PaginationItem>
      </PaginationContent>
    </Pagination>
  );
}
