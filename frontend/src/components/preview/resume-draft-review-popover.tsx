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
} from "./resume-draft-review-dom";
import {
  useResumeDraftReviewDecoration,
  type ResumeDraftReviewTarget as ReviewTarget,
} from "./use-resume-draft-review-decoration";

export interface ResumeDraftReviewPresentation {
  exitingReviewItemIds?: readonly string[];
  onSelectReviewItem?: (reviewItemId: string) => void;
  reviewItemIdByOperationId: Readonly<Record<string, string>>;
  selectedReviewItemId?: string;
}

const EMPTY_REVIEW_ITEM_MAP: Readonly<Record<string, string>> = {};
const EMPTY_REVIEW_ITEM_IDS: readonly string[] = [];

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

  useResumeDraftReviewDecoration({
    activeElement: activeTarget?.element ?? null,
    exitingReviewItemIds,
    inspectLabel: t.agentDiffInspect,
    onPinnedTargetReplace: setPinnedTarget,
    pinnedTargetRef,
    previewRef,
    resolveTarget,
    reviewPopoverId,
    selectedReviewItemId,
  });

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
