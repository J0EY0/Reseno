import {
  Popover,
  PopoverAnchor,
  PopoverContent,
} from "@/components/ui/popover";
import type { AppMessages } from "@/i18n";
import { compactResumeDraftDiffs } from "@/lib/agent-diff-value";
import type { ResumeDraftDiff } from "@/types/resume";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useId,
  type FocusEvent as ReactFocusEvent,
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent as ReactMouseEvent,
  type PointerEvent as ReactPointerEvent,
  type RefObject,
} from "react";

import { ResumeDraftReviewComparison } from "./resume-draft-review-comparison";
import {
  getResumeDraftReviewPaths,
  getResumeDraftReviewTargetElement,
  isVisibleResumeDraftReviewTarget,
} from "./resume-draft-review-dom";

export interface ResumeDraftReviewPresentation {
  exitingReviewItemIds?: readonly string[];
  onSelectReviewItem?: (reviewItemId: string) => void;
  reviewItemIdByOperationId: Readonly<Record<string, string>>;
  selectedReviewItemId?: string;
}

interface ReviewTarget {
  diff: ResumeDraftDiff;
  element: HTMLElement;
  reviewItemId?: string;
}

const EMPTY_REVIEW_ITEM_MAP: Readonly<Record<string, string>> = {};
const EMPTY_REVIEW_ITEM_IDS: readonly string[] = [];

function prefersReducedMotion() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export function useResumeDraftReviewInteraction({
  diffs,
  presentation,
  previewRef,
  t,
}: {
  diffs?: ResumeDraftDiff[];
  presentation?: ResumeDraftReviewPresentation;
  previewRef: RefObject<HTMLElement | null>;
  t: AppMessages;
}) {
  const compactedDiffs = useMemo(
    () => compactResumeDraftDiffs(diffs ?? []),
    [diffs],
  );
  const diffByPath = useMemo(
    () => new Map(compactedDiffs.map((diff) => [diff.path, diff])),
    [compactedDiffs],
  );
  const onSelectReviewItem = presentation?.onSelectReviewItem;
  const exitingReviewItemIds =
    presentation?.exitingReviewItemIds ?? EMPTY_REVIEW_ITEM_IDS;
  const reviewItemIdByOperationId =
    presentation?.reviewItemIdByOperationId ?? EMPTY_REVIEW_ITEM_MAP;
  const selectedReviewItemId = presentation?.selectedReviewItemId;
  const reviewPopoverId = useId();
  const [hoveredTarget, setHoveredTarget] = useState<ReviewTarget | null>(null);
  const [pinnedTarget, setPinnedTarget] = useState<ReviewTarget | null>(null);
  const hoverCloseTimerRef = useRef<number | null>(null);
  const currentPinnedDiff = pinnedTarget
    ? diffByPath.get(pinnedTarget.diff.path)
    : undefined;
  const currentPinnedReviewItemId = currentPinnedDiff
    ? reviewItemIdByOperationId[currentPinnedDiff.operationId]
    : undefined;
  const effectivePinnedTarget = useMemo(
    () =>
      pinnedTarget &&
      currentPinnedDiff &&
      (!pinnedTarget.reviewItemId ||
        currentPinnedReviewItemId === pinnedTarget.reviewItemId)
        ? {
            ...pinnedTarget,
            diff: currentPinnedDiff,
            reviewItemId: currentPinnedReviewItemId,
          }
        : null,
    [currentPinnedDiff, currentPinnedReviewItemId, pinnedTarget],
  );
  const currentHoveredDiff = hoveredTarget
    ? diffByPath.get(hoveredTarget.diff.path)
    : undefined;
  const currentHoveredReviewItemId = currentHoveredDiff
    ? reviewItemIdByOperationId[currentHoveredDiff.operationId]
    : undefined;
  const effectiveHoveredTarget = useMemo(
    () =>
      hoveredTarget &&
      hoveredTarget.element.isConnected &&
      currentHoveredDiff &&
      (!hoveredTarget.reviewItemId ||
        currentHoveredReviewItemId === hoveredTarget.reviewItemId)
        ? {
            ...hoveredTarget,
            diff: currentHoveredDiff,
            reviewItemId: currentHoveredReviewItemId,
          }
        : null,
    [currentHoveredDiff, currentHoveredReviewItemId, hoveredTarget],
  );
  const pinnedTargetRef = useRef(effectivePinnedTarget);
  const lastRevealedItemIdRef = useRef<string | null>(null);
  const activeTarget = effectivePinnedTarget ?? effectiveHoveredTarget;
  const virtualAnchorRef = useMemo(
    () => (activeTarget ? { current: activeTarget.element } : null),
    [activeTarget],
  );

  const resolveTarget = useCallback(
    (element: HTMLElement | null): ReviewTarget | null => {
      if (!element) {
        return null;
      }
      const diff = getResumeDraftReviewPaths(element)
        .map((path) => diffByPath.get(path))
        .filter(Boolean)
        .at(-1);
      if (!diff) {
        return null;
      }
      return {
        diff,
        element,
        reviewItemId:
          reviewItemIdByOperationId[diff.operationId],
      };
    },
    [diffByPath, reviewItemIdByOperationId],
  );

  const clearHoverTimer = useCallback(() => {
    if (hoverCloseTimerRef.current !== null) {
      window.clearTimeout(hoverCloseTimerRef.current);
      hoverCloseTimerRef.current = null;
    }
  }, []);

  const scheduleHoverClose = useCallback(() => {
    clearHoverTimer();
    hoverCloseTimerRef.current = window.setTimeout(() => {
      setHoveredTarget(null);
      hoverCloseTimerRef.current = null;
    }, 80);
  }, [clearHoverTimer]);

  useEffect(() => clearHoverTimer, [clearHoverTimer]);
  useEffect(() => {
    pinnedTargetRef.current = effectivePinnedTarget;
  }, [effectivePinnedTarget]);
  useEffect(() => {
    if (
      (!hoveredTarget || effectiveHoveredTarget) &&
      (!pinnedTarget || effectivePinnedTarget)
    ) {
      return;
    }

    const frame = window.requestAnimationFrame(() => {
      if (hoveredTarget && !effectiveHoveredTarget) {
        setHoveredTarget(null);
      }
      if (pinnedTarget && !effectivePinnedTarget) {
        setPinnedTarget(null);
      }
    });

    return () => window.cancelAnimationFrame(frame);
  }, [
    effectiveHoveredTarget,
    effectivePinnedTarget,
    hoveredTarget,
    pinnedTarget,
  ]);

  useEffect(() => {
    const root = previewRef.current;
    if (!root) {
      return;
    }
    const exitingIds = new Set(exitingReviewItemIds);

    const decorate = () => {
      for (const element of root.querySelectorAll<HTMLElement>(
        "[data-resume-diff-path]",
      )) {
        if (element.closest("[inert]")) {
          continue;
        }
        const target = resolveTarget(element);
        if (!target) {
          continue;
        }

        element.classList.add("resume-diff-review-target");
        element.dataset.resumeReviewDecorated = "true";
        if (target.reviewItemId) {
          element.dataset.resumeReviewItemId = target.reviewItemId;
        }
        if (target.reviewItemId === selectedReviewItemId) {
          element.dataset.resumeReviewSelected = "true";
        } else {
          delete element.dataset.resumeReviewSelected;
        }
        if (target.reviewItemId && exitingIds.has(target.reviewItemId)) {
          element.dataset.resumeReviewState = "exiting";
        } else {
          delete element.dataset.resumeReviewState;
        }

        const ancestorTarget = element.parentElement?.closest<HTMLElement>(
          "[data-resume-diff-path]",
        );
        if (!ancestorTarget && isVisibleResumeDraftReviewTarget(element)) {
          element.tabIndex = 0;
          element.setAttribute("role", "button");
          element.setAttribute(
            "aria-label",
            t.agentDiffInspect.replace("{label}", target.diff.label),
          );
          element.setAttribute("aria-controls", reviewPopoverId);
          element.setAttribute("aria-expanded", "false");
          element.setAttribute("aria-haspopup", "dialog");
          element.dataset.resumeReviewTabStop = "true";
        }
      }

      const selectedItemId = selectedReviewItemId;
      if (!selectedItemId) {
        lastRevealedItemIdRef.current = null;
      } else if (lastRevealedItemIdRef.current !== selectedItemId) {
        const selectedElement = [
          ...root.querySelectorAll<HTMLElement>(
            '[data-resume-review-item-id]',
          ),
        ].find(
          (element) =>
            element.dataset.resumeReviewItemId === selectedItemId &&
            isVisibleResumeDraftReviewTarget(element),
        );
        if (selectedElement) {
          selectedElement.scrollIntoView({
            behavior: prefersReducedMotion() ? "auto" : "smooth",
            block: "center",
            inline: "nearest",
          });
          lastRevealedItemIdRef.current = selectedItemId;
        }
      }

      const pinned = pinnedTargetRef.current;
      if (pinned && !pinned.element.isConnected) {
        const replacement = [
          ...root.querySelectorAll<HTMLElement>("[data-resume-diff-path]"),
        ].find(
          (element) =>
            getResumeDraftReviewPaths(element).includes(pinned.diff.path) &&
            isVisibleResumeDraftReviewTarget(element),
        );
        const replacementTarget = resolveTarget(replacement ?? null);
        if (replacementTarget) {
          setPinnedTarget(replacementTarget);
        }
      }
    };

    decorate();
    const observer = new MutationObserver(decorate);
    observer.observe(root, { childList: true, subtree: true });

    return () => {
      observer.disconnect();
      for (const element of root.querySelectorAll<HTMLElement>(
        '[data-resume-review-decorated="true"]',
      )) {
        element.classList.remove("resume-diff-review-target");
        delete element.dataset.resumeReviewDecorated;
        delete element.dataset.resumeReviewItemId;
        delete element.dataset.resumeReviewSelected;
        delete element.dataset.resumeReviewState;
        if (element.dataset.resumeReviewTabStop === "true") {
          element.removeAttribute("aria-label");
          element.removeAttribute("aria-controls");
          element.removeAttribute("aria-describedby");
          element.removeAttribute("aria-expanded");
          element.removeAttribute("aria-haspopup");
          element.removeAttribute("role");
          element.removeAttribute("tabindex");
          delete element.dataset.resumeReviewTabStop;
        }
      }
    };
  }, [
    previewRef,
    resolveTarget,
    exitingReviewItemIds,
    reviewPopoverId,
    selectedReviewItemId,
    t.agentDiffInspect,
  ]);

  useEffect(() => {
    const root = previewRef.current;
    if (!root) {
      return;
    }
    for (const element of root.querySelectorAll<HTMLElement>(
      '[data-resume-review-tab-stop="true"]',
    )) {
      const expanded = activeTarget?.element === element;
      element.setAttribute("aria-expanded", String(expanded));
      if (expanded) {
        element.setAttribute("aria-describedby", reviewPopoverId);
      } else {
        element.removeAttribute("aria-describedby");
      }
    }
  }, [activeTarget?.element, previewRef, reviewPopoverId]);

  const onPointerOver = useCallback(
    (event: ReactPointerEvent<HTMLElement>) => {
      if (effectivePinnedTarget) {
        return;
      }
      clearHoverTimer();
      setHoveredTarget(
        resolveTarget(
          getResumeDraftReviewTargetElement(event.target, previewRef.current),
        ),
      );
    }, [clearHoverTimer, effectivePinnedTarget, previewRef, resolveTarget],
  );
  const onPointerOut = useCallback(
    (event: ReactPointerEvent<HTMLElement>) => {
      if (effectivePinnedTarget) {
        return;
      }
      const from = getResumeDraftReviewTargetElement(
        event.target,
        previewRef.current,
      );
      const to = getResumeDraftReviewTargetElement(
        event.relatedTarget,
        previewRef.current,
      );
      if (from && from === to) {
        return;
      }
      scheduleHoverClose();
    }, [effectivePinnedTarget, previewRef, scheduleHoverClose],
  );
  const onFocus = useCallback(
    (event: ReactFocusEvent<HTMLElement>) => {
      if (!effectivePinnedTarget) {
        setHoveredTarget(
          resolveTarget(
            getResumeDraftReviewTargetElement(event.target, previewRef.current),
          ),
        );
      }
    }, [effectivePinnedTarget, previewRef, resolveTarget],
  );
  const onBlur = useCallback(
    (event: ReactFocusEvent<HTMLElement>) => {
      if (!effectivePinnedTarget) {
        const to = getResumeDraftReviewTargetElement(
          event.relatedTarget,
          previewRef.current,
        );
        if (!to) {
          scheduleHoverClose();
        }
      }
    }, [effectivePinnedTarget, previewRef, scheduleHoverClose],
  );
  const pinTarget = useCallback(
    (element: HTMLElement | null) => {
      const target = resolveTarget(element);
      if (!target) {
        return;
      }
      clearHoverTimer();
      setHoveredTarget(target);
      setPinnedTarget(target);
      if (target.reviewItemId) {
        onSelectReviewItem?.(target.reviewItemId);
      }
    }, [clearHoverTimer, onSelectReviewItem, resolveTarget],
  );
  const onClick = useCallback(
    (event: ReactMouseEvent<HTMLElement>) => {
      const element = getResumeDraftReviewTargetElement(
        event.target,
        previewRef.current,
      );
      if (!element) {
        return;
      }
      event.preventDefault();
      event.stopPropagation();
      pinTarget(element);
    }, [pinTarget, previewRef],
  );
  const onKeyDown = useCallback(
    (event: ReactKeyboardEvent<HTMLElement>) => {
      if (event.key !== "Enter" && event.key !== " ") {
        return;
      }
      const element = getResumeDraftReviewTargetElement(
        event.target,
        previewRef.current,
      );
      if (!element) {
        return;
      }
      event.preventDefault();
      event.stopPropagation();
      pinTarget(element);
    }, [pinTarget, previewRef],
  );

  return {
    onBlur,
    onClick,
    onFocus,
    onKeyDown,
    onPointerOut,
    onPointerOver,
    popover: (
      <Popover
        onOpenChange={(open) => {
          if (!open) {
            setHoveredTarget(null);
            setPinnedTarget(null);
          }
        }}
        open={Boolean(activeTarget)}
      >
        {virtualAnchorRef ? (
          <PopoverAnchor virtualRef={virtualAnchorRef} />
        ) : null}
        {activeTarget ? (
          <PopoverContent
            align="center"
            className="w-[min(22rem,calc(100vw-2rem))] p-3"
            collisionPadding={16}
            id={reviewPopoverId}
            onFocusCapture={clearHoverTimer}
            onCloseAutoFocus={(event) => event.preventDefault()}
            onOpenAutoFocus={(event) => event.preventDefault()}
            onPointerEnter={clearHoverTimer}
            onPointerLeave={() => {
              if (!effectivePinnedTarget) {
                scheduleHoverClose();
              }
            }}
            side="top"
            sideOffset={8}
          >
            <ResumeDraftReviewComparison diff={activeTarget.diff} t={t} />
          </PopoverContent>
        ) : null}
      </Popover>
    ),
  };
}
