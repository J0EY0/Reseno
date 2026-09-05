import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";

import { getAdjacentAgentDraftReviewItemId } from "@/lib/agent-draft-review";
import type { AgentDraftReviewItem } from "@/types/api";

const REVIEW_SELECTION_EXIT_MS = 180;

interface AgentDraftReviewSelection {
  mode: "all" | "single";
  reviewItemId: string | null;
}

function prefersReducedMotion() {
  return (
    typeof window === "undefined" ||
    typeof window.matchMedia !== "function" ||
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

export function waitForAgentDraftReviewExit() {
  if (prefersReducedMotion()) {
    return Promise.resolve();
  }

  return new Promise<void>((resolve) => {
    window.setTimeout(resolve, REVIEW_SELECTION_EXIT_MS);
  });
}

export function useAgentDraftReviewSelection({
  decisionPending,
  pendingItems,
}: {
  decisionPending: boolean;
  pendingItems: AgentDraftReviewItem[];
}) {
  const [selection, setSelection] = useState<AgentDraftReviewSelection>({
    mode: "all",
    reviewItemId: null,
  });
  const [exitingReviewItemIds, setExitingReviewItemIds] = useState<string[]>([]);
  const [isTransitioning, setIsTransitioning] = useState(false);
  const decisionPendingRef = useRef(decisionPending);
  const pendingItemsRef = useRef(pendingItems);
  const selectionRef = useRef(selection);
  const transitionTimerRef = useRef<number | null>(null);
  useLayoutEffect(() => {
    decisionPendingRef.current = decisionPending;
    pendingItemsRef.current = pendingItems;
    selectionRef.current = selection;
  }, [decisionPending, pendingItems, selection]);

  const clearTransitionTimer = useCallback(() => {
    if (transitionTimerRef.current !== null) {
      window.clearTimeout(transitionTimerRef.current);
      transitionTimerRef.current = null;
    }
  }, []);
  const cancelSelectionTransition = useCallback(() => {
    clearTransitionTimer();
    setIsTransitioning(false);
    setExitingReviewItemIds([]);
  }, [clearTransitionTimer]);
  const commitSelection = useCallback((next: AgentDraftReviewSelection) => {
    selectionRef.current = next;
    setSelection(next);
  }, []);

  useEffect(() => clearTransitionTimer, [clearTransitionTimer]);

  const transitionToItem = useCallback(
    (reviewItemId: string) => {
      if (decisionPendingRef.current || transitionTimerRef.current !== null) {
        return;
      }
      const items = pendingItemsRef.current;
      if (!items.some((item) => item.id === reviewItemId)) {
        return;
      }

      const current = selectionRef.current;
      if (current.mode === "single" && current.reviewItemId === reviewItemId) {
        return;
      }
      const exitingIds = current.mode === "all"
        ? items
            .filter((item) => item.id !== reviewItemId)
            .map((item) => item.id)
        : current.reviewItemId
          ? [current.reviewItemId]
          : [];
      const next = { mode: "single", reviewItemId } as const;

      if (exitingIds.length === 0 || prefersReducedMotion()) {
        commitSelection(next);
        return;
      }

      // Keep the current projection mounted while its review highlights exit;
      // the timer commits the next projection only after that visual state ends.
      setIsTransitioning(true);
      setExitingReviewItemIds(exitingIds);
      transitionTimerRef.current = window.setTimeout(() => {
        transitionTimerRef.current = null;
        const nextItems = pendingItemsRef.current;
        const nextItemId = nextItems.some((item) => item.id === reviewItemId)
          ? reviewItemId
          : nextItems[0]?.id ?? null;
        commitSelection(
          nextItemId
            ? { mode: "single", reviewItemId: nextItemId }
            : { mode: "all", reviewItemId: null },
        );
        setIsTransitioning(false);
        setExitingReviewItemIds([]);
      }, REVIEW_SELECTION_EXIT_MS);
    },
    [commitSelection],
  );

  const showAll = useCallback(() => {
    if (decisionPendingRef.current) {
      return;
    }
    cancelSelectionTransition();
    commitSelection({ mode: "all", reviewItemId: null });
  }, [cancelSelectionTransition, commitSelection]);
  const selectFirst = useCallback(() => {
    const firstItem = pendingItemsRef.current[0];
    if (firstItem) {
      transitionToItem(firstItem.id);
    }
  }, [transitionToItem]);
  const selectAdjacent = useCallback(
    (direction: -1 | 1) => {
      const nextItemId = getAdjacentAgentDraftReviewItemId(
        pendingItemsRef.current,
        selectionRef.current.mode === "single"
          ? selectionRef.current.reviewItemId
          : null,
        direction,
      );
      if (nextItemId) {
        transitionToItem(nextItemId);
      }
    },
    [transitionToItem],
  );
  const selectPrevious = useCallback(() => selectAdjacent(-1), [selectAdjacent]);
  const selectNext = useCallback(() => selectAdjacent(1), [selectAdjacent]);

  const reset = useCallback(() => {
    cancelSelectionTransition();
    commitSelection({ mode: "all", reviewItemId: null });
  }, [cancelSelectionTransition, commitSelection]);
  const reconcile = useCallback(
    (nextItems: AgentDraftReviewItem[], resetToAll: boolean) => {
      cancelSelectionTransition();
      if (resetToAll || selectionRef.current.mode === "all") {
        commitSelection({ mode: "all", reviewItemId: null });
        return;
      }
      const selectedId = selectionRef.current.reviewItemId;
      commitSelection({
        mode: "single",
        reviewItemId:
          nextItems.find((item) => item.id === selectedId)?.id ??
          nextItems[0]?.id ??
          null,
      });
    },
    [cancelSelectionTransition, commitSelection],
  );
  const adoptResolvedItems = useCallback(
    (nextItems: AgentDraftReviewItem[], successorId: string | null) => {
      cancelSelectionTransition();
      const nextItemId =
        nextItems.find((item) => item.id === successorId)?.id ??
        nextItems[0]?.id ??
        null;
      commitSelection(
        nextItemId
          ? { mode: "single", reviewItemId: nextItemId }
          : { mode: "all", reviewItemId: null },
      );
    },
    [cancelSelectionTransition, commitSelection],
  );
  const beginDecisionExit = useCallback((reviewItemIds: string[]) => {
    if (transitionTimerRef.current !== null || decisionPendingRef.current) {
      return false;
    }
    // Decisions and review navigation share one outgoing-region channel so
    // the preview never runs competing animations for the same operation.
    setExitingReviewItemIds(
      prefersReducedMotion() ? [] : [...reviewItemIds],
    );
    return true;
  }, []);
  const endDecisionExit = useCallback(() => {
    setExitingReviewItemIds([]);
  }, []);

  const selectedItem = selection.mode === "single"
    ? pendingItems.find((item) => item.id === selection.reviewItemId) ??
      pendingItems[0] ??
      null
    : null;

  return {
    adoptResolvedItems,
    beginDecisionExit,
    endDecisionExit,
    exitingReviewItemIds,
    isTransitioning,
    mode: selectedItem ? "single" as const : "all" as const,
    reconcile,
    reset,
    selectFirst,
    selectItem: transitionToItem,
    selectNext,
    selectPrevious,
    selectedIndex: selectedItem
      ? pendingItems.findIndex((item) => item.id === selectedItem.id)
      : -1,
    selectedItem,
    selectedItemId: selectedItem?.id ?? null,
    showAll,
  };
}
